from datetime import datetime, timedelta
import math
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from psycopg2.extras import RealDictCursor
from app.routes.auth import enviar_alerta_sistema
# Nossos módulos
from ..services.crm_service import CRMService
from app.utils.db import get_db_connection

crm_bp = Blueprint('crm', __name__)

# ==========================================
# BLOCO 1: HELPERS INTERNOS E CONTEXTO
# ==========================================

def obter_contexto_acesso():
    """
    Recupera o contexto do usuário logado, garante segurança Multitenant 
    e define permissões base de acesso.
    """
    if 'user_id' not in session:
        return None
    
    role = session.get('role')
    permissoes = {
        # Adicionei 'assessor' e 'master' na lista de permissões do mapa
        "permite_mapa": True if role in ['candidato', 'coordenador', 'superadmin', 'master', 'assessor'] else False,
        "permite_equipe": True if role in ['candidato', 'coordenador', 'superadmin', 'master'] else False,
        "permite_bi": True if role in ['candidato', 'superadmin', 'master'] else False
    }

    return {
        "user_id": session.get('user_id'),
        "cliente_id": session.get('cliente_id'),
        "role": role,
        "permissoes": permissoes
    }

def _parse_date(date_val):
    """Utilitário para padronizar datas vindas do PostgreSQL para o Jinja2."""
    if not date_val:
        return None
    if isinstance(date_val, str):
        try:
            return datetime.strptime(date_val[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    elif isinstance(date_val, datetime):
        return date_val.date()
    return date_val

# ==========================================
# BLOCO 2: DASHBOARD E GEOINTELIGÊNCIA
# ==========================================

@crm_bp.route('/dashboard') 
def dashboard_index():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
        
    resumo = CRMService.get_dashboard_data(ctx['cliente_id'])
    return render_template('crm/dashboard.html', resumo=resumo, permissoes=ctx['permissoes'])

@crm_bp.route('/mapa')
def mapa_bairros():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    if not ctx['permissoes']['permite_mapa']:
        flash('Seu perfil não tem acesso ao mapa.', 'warning')
        return redirect(url_for('crm.dashboard_index'))

    dados_mapa = CRMService.get_dados_mapa(ctx['cliente_id'])
    return render_template('crm/mapa.html', dados_mapa=dados_mapa, permissoes=ctx['permissoes'])


# ==========================================
# BLOCO 3: GESTÃO DE EQUIPE (HIERARQUIA)
# ==========================================

@crm_bp.route('/equipe', methods=['GET'])
def listar_equipe():
    """Carrega a equipe filtrando hierarquia (Candidato vs Assessor)."""
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
        
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.', 'danger')
        return redirect(url_for('crm.dashboard_index'))

    equipe = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if ctx['role'] == 'candidato':
                cursor.execute("""
                    SELECT id, nome, email, telefone, cpf, role, status 
                    FROM usuarios 
                    WHERE cliente_id = %s AND role != 'candidato' AND id != %s
                    ORDER BY nome ASC
                """, (ctx['cliente_id'], ctx['user_id']))
            else:
                cursor.execute("""
                    SELECT id, nome, email, telefone, cpf, role, status 
                    FROM usuarios 
                    WHERE cliente_id = %s AND id != %s
                    ORDER BY CASE WHEN role = 'candidato' THEN 1 ELSE 2 END, nome ASC
                """, (ctx['cliente_id'], ctx['user_id']))
                
            equipe = cursor.fetchall()
    except Exception as e:
        print(f"❌ Erro ao carregar equipe no CRM: {e}")
        flash('Erro técnico ao carregar a equipe.', 'danger')
    finally:
        conn.close()

    return render_template('crm/equipe.html', equipe=equipe, permissoes=ctx['permissoes'], role_logado=ctx['role'])


# ==========================================
# BLOCO 4: GESTÃO DE APOIADORES
# ==========================================

@crm_bp.route('/apoiadores')
def listar_apoiadores():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    apoiadores = CRMService.get_apoiadores(ctx['cliente_id'])
    return render_template('crm/apoiadores.html', apoiadores=apoiadores, permissoes=ctx['permissoes'])

@crm_bp.route('/apoiadores/novo', methods=['GET', 'POST'])
def novo_apoiador():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        CRMService.adicionar_apoiador(ctx['cliente_id'], request.form)
        return redirect(url_for('crm.listar_apoiadores'))
        
    return render_template('crm/form_apoiador.html', permissoes=ctx['permissoes'])

@crm_bp.route('/apoiadores/<apoiador_id>')
def perfil_apoiador(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Dados Básicos
            cursor.execute("SELECT * FROM apoiadores WHERE id = %s AND cliente_id = %s", (apoiador_id, ctx['cliente_id']))
            apoiador = cursor.fetchone()
            if not apoiador:
                flash('Apoiador não encontrado.', 'danger')
                return redirect(url_for('crm.listar_apoiadores'))
            
            apoiador['data_cadastro'] = _parse_date(apoiador.get('data_cadastro'))

            # 2. Interações
            cursor.execute("""
                SELECT i.*, u.nome as usuario_nome FROM apoiador_interacoes i
                LEFT JOIN usuarios u ON i.usuario_id = u.id
                WHERE i.apoiador_id = %s ORDER BY i.data_registro DESC
            """, (apoiador_id,))
            interacoes = cursor.fetchall()

            # 3. Resumo Tarefas
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'pendente' THEN 1 ELSE 0 END) as pendentes,
                       SUM(CASE WHEN status = 'atrasada' THEN 1 ELSE 0 END) as atrasadas
                FROM tarefas WHERE apoiador_id = %s
            """, (apoiador_id,))
            resumo_tarefas = cursor.fetchone()

            # 4. Lista Tarefas
            cursor.execute("""
                SELECT t.id, t.tipo, t.status, t.data_limite, u.nome as delegado_nome
                FROM tarefas t LEFT JOIN usuarios u ON t.assessor_id = u.id
                WHERE t.apoiador_id = %s ORDER BY t.data_limite DESC NULLS LAST
            """, (apoiador_id,))
            tarefas_vinculadas = cursor.fetchall()
            for t in tarefas_vinculadas:
                t['data_limite'] = _parse_date(t.get('data_limite'))

            # 5. Assessores para Modais
            cursor.execute("SELECT id, nome FROM usuarios WHERE cliente_id = %s", (ctx['cliente_id'],))
            assessores = cursor.fetchall()
            
    finally:
        if conn: conn.close()
        
    return render_template('crm/perfil_apoiador.html', 
                           apoiador=apoiador, interacoes=interacoes, 
                           resumo=resumo_tarefas, tarefas_vinculadas=tarefas_vinculadas, 
                           assessores=assessores, permissoes=ctx['permissoes'])

@crm_bp.route('/apoiadores/<apoiador_id>/editar', methods=['POST'])
def editar_apoiador(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    tags_list = request.form.getlist('tags')
    dados = {**request.form.to_dict(), 
             'oferece_muro': 'on' in request.form,
             'oferece_carro': 'on' in request.form,
             'lideranca': 'on' in request.form,
             'tags': ",".join(tags_list) if tags_list else None}

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE apoiadores SET 
                    nome=%(nome)s, telefone=%(telefone)s, indicado_por=%(indicado_por)s, sexo=%(sexo)s, 
                    faixa_etaria=%(faixa_etaria)s, renda_familiar=%(renda_familiar)s, grau_instrucao=%(grau_instrucao)s, 
                    origem_cadastro=%(origem_cadastro)s, posicionamento_politico=%(posicionamento_politico)s, 
                    cep=%(cep)s, logradouro=%(logradouro)s, numero=%(numero)s, complemento=%(complemento)s, 
                    bairro=%(bairro)s, cidade=%(cidade)s, uf=%(uf)s, grau_apoio=%(grau_apoio)s, 
                    votos_familia=%(votos_familia)s, oferece_muro=%(oferece_muro)s, oferece_carro=%(oferece_carro)s, 
                    lideranca=%(lideranca)s, observacoes=%(observacoes)s, tags=%(tags)s
                WHERE id = %(id)s AND cliente_id = %(cliente_id)s
            """, {**dados, 'id': apoiador_id, 'cliente_id': ctx['cliente_id']})
        conn.commit()
        flash('Perfil atualizado com sucesso!', 'success')
    except Exception as e:
        print(f"Erro ao editar apoiador: {e}")
        flash('Erro ao atualizar dados.', 'danger')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

@crm_bp.route('/apoiadores/<id>/editar-perfil', methods=['POST'])
def editar_perfil_detalhado(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    CRMService.atualizar_perfil_demografico(ctx['cliente_id'], id, request.form)
    flash('Perfil demográfico atualizado com sucesso!', 'success')
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=id))

@crm_bp.route('/apoiadores/<id>/editar-cadastro', methods=['POST'])
def editar_cadastro_geral(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    CRMService.atualizar_cadastro_geral(ctx['cliente_id'], id, request.form)
    flash('Dados cadastrais e endereço atualizados com sucesso.', 'success')
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=id))

@crm_bp.route('/apoiadores/excluir/<apoiador_id>', methods=['POST'])
def excluir_apoiador(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    CRMService.excluir_apoiador(ctx['cliente_id'], apoiador_id)
    flash('Apoiador excluído permanentemente.', 'warning')
    return redirect(url_for('crm.listar_apoiadores'))

@crm_bp.route('/apoiadores/<apoiador_id>/interacao', methods=['POST'])
def registrar_interacao(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conteudo = request.form.get('conteudo')
    tipo = request.form.get('tipo', 'Nota')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO apoiador_interacoes (apoiador_id, usuario_id, tipo, conteudo)
                VALUES (%s, %s, %s, %s)
            """, (apoiador_id, ctx['user_id'], tipo, conteudo))
        conn.commit()
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))


# ==========================================
# BLOCO 5: GESTÃO DE TAREFAS (CRIAÇÃO/EDICAO)
# ==========================================

@crm_bp.route('/apoiadores/<apoiador_id>/tarefa/nova', methods=['POST'])
def criar_tarefa_perfil(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    assessor_id = request.form.get('assessor_id')
    tipo_tarefa = request.form.get('tipo')
    descricao_tarefa = request.form.get('descricao')
    data_limite = request.form.get('data_limite')

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Busca os dados do Assessor que vai receber a tarefa
            cursor.execute("SELECT nome, email FROM usuarios WHERE id = %s", (assessor_id,))
            assessor = cursor.fetchone()

            # 2. Insere a tarefa no banco
            cursor.execute("""
                INSERT INTO tarefas (id, cliente_id, criador_id, assessor_id, apoiador_id, tipo, descricao, status, data_limite)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, 'pendente', %s)
            """, (ctx['cliente_id'], ctx['user_id'], assessor_id, apoiador_id, 
                  tipo_tarefa, descricao_tarefa, data_limite))
            
            conn.commit()

            # 3. Dispara o e-mail se o assessor foi encontrado
            if assessor and assessor['email']:
                enviar_alerta_sistema(
                    destinatario=assessor['email'],
                    nome_usuario=assessor['nome'],
                    tipo_alerta="📅 Nova Tarefa Atribuída",
                    descricao=f"Você tem uma nova missão: <b>{tipo_tarefa}</b>.<br>Detalhes: {descricao_tarefa}<br>Prazo: {data_limite}"
                )

        flash('Tarefa agendada e assessor notificado!', 'success')
    except Exception as e:
        print(f"Erro ao criar tarefa e notificar: {e}")
        flash('Erro ao criar tarefa.', 'danger')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

@crm_bp.route('/apoiadores/<apoiador_id>/tarefas', methods=['POST'])
def nova_tarefa(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    CRMService.adicionar_tarefa(ctx['cliente_id'], apoiador_id, request.form)
    flash('Tarefa adicionada com sucesso!', 'success')
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))


# ==========================================
# BLOCO 6: PAINEL GLOBAL DE TAREFAS
# ==========================================

@crm_bp.route('/tarefas', methods=['GET'])
def listar_todas_tarefas():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    tarefas = []
    
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    kpis = {'total': 0, 'atrasadas': 0, 'concluidas': 0}
    total_pages = 1
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Atualiza status de atrasadas em massa
            cursor.execute("""
                UPDATE tarefas SET status = 'atrasada' 
                WHERE cliente_id = %s AND status = 'pendente' 
                AND NULLIF(data_limite, '')::DATE < CURRENT_DATE
            """, (ctx['cliente_id'],))
            conn.commit()

            # Métricas
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'atrasada' THEN 1 ELSE 0 END) as atrasadas,
                       SUM(CASE WHEN status IN ('concluida', 'concluído') THEN 1 ELSE 0 END) as concluidas
                FROM tarefas WHERE cliente_id = %s
            """, (ctx['cliente_id'],))
            kpis_db = cursor.fetchone()
            
            if kpis_db:
                kpis.update({k: v or 0 for k, v in kpis_db.items()})
                
            total_pages = math.ceil(kpis['total'] / per_page) if kpis['total'] > 0 else 1

            # Busca Paginada
            cursor.execute("""
                SELECT t.id, t.tipo, t.status, t.data_limite, u.nome as delegado_nome, a.nome as apoiador_nome
                FROM tarefas t
                LEFT JOIN usuarios u ON t.assessor_id = u.id
                LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                WHERE t.cliente_id = %s
                ORDER BY CASE WHEN t.status = 'atrasada' THEN 1 WHEN t.status = 'pendente' THEN 2 ELSE 3 END,
                         NULLIF(t.data_limite, '')::DATE ASC NULLS LAST
                LIMIT %s OFFSET %s
            """, (ctx['cliente_id'], per_page, offset))
            tarefas = cursor.fetchall()
            
            for t in tarefas:
                t['data_limite'] = _parse_date(t.get('data_limite'))
                
    except Exception as e:
        print(f"Erro ao carregar tarefas: {e}")
    finally:
        if conn: conn.close()
        
    return render_template('crm/tarefas_lista.html', 
                           tarefas=tarefas, kpis=kpis, page=page, 
                           total_pages=total_pages, permissoes=ctx['permissoes'])

@crm_bp.route('/tarefas/<tarefa_id>', methods=['GET'])
def detalhe_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Dados Principais
            cursor.execute("""
                SELECT t.*, u_assessor.nome as delegado_nome, u_criador.nome as criador_nome, a.nome as apoiador_nome
                FROM tarefas t
                LEFT JOIN usuarios u_assessor ON t.assessor_id = u_assessor.id
                LEFT JOIN usuarios u_criador ON t.criador_id = u_criador.id
                LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                WHERE t.id = %s AND t.cliente_id = %s
            """, (tarefa_id, ctx['cliente_id']))
            tarefa = cursor.fetchone()
            
            if not tarefa:
                flash('Tarefa não encontrada.', 'danger')
                return redirect(url_for('crm.listar_todas_tarefas'))

            tarefa['data_limite'] = _parse_date(tarefa.get('data_limite'))

            # Dependências
            cursor.execute("SELECT m.*, u.nome FROM tarefa_membros m JOIN usuarios u ON m.usuario_id = u.id WHERE m.tarefa_id = %s", (tarefa_id,))
            membros = cursor.fetchall()

            cursor.execute("SELECT c.*, u.nome FROM tarefa_chat c JOIN usuarios u ON c.usuario_id = u.id WHERE c.tarefa_id = %s ORDER BY data_envio ASC", (tarefa_id,))
            mensagens_chat = cursor.fetchall()
            
            cursor.execute("SELECT p.*, u.nome FROM tarefa_pedidos_acesso p JOIN usuarios u ON p.usuario_id = u.id WHERE p.tarefa_id = %s AND p.status = 'pendente'", (tarefa_id,))
            pedidos = cursor.fetchall()

            cursor.execute("SELECT id, nome FROM usuarios WHERE cliente_id = %s", (ctx['cliente_id'],))
            usuarios_equipa = cursor.fetchall()

            is_owner = (tarefa['assessor_id'] == ctx['user_id'] or tarefa.get('criador_id') == ctx['user_id'])
            is_admin = any(m['usuario_id'] == ctx['user_id'] and m['papel'] == 'admin' for m in membros)
            pode_editar = is_owner or is_admin

    except Exception as e:
        print(f"Erro detalhe tarefa: {e}")
        flash('Erro ao carregar dados.', 'danger')
        return redirect(url_for('crm.listar_todas_tarefas'))
    finally:
        if conn: conn.close()
        
    return render_template('crm/tarefa_view.html', 
                           tarefa=tarefa, membros=membros, mensagens=mensagens_chat, 
                           pode_editar=pode_editar, pedidos=pedidos, usuarios_equipa=usuarios_equipa, 
                           user_id=ctx['user_id'], permissoes=ctx['permissoes'])

@crm_bp.route('/tarefas/<tarefa_id>/editar', methods=['POST'])
def editar_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tarefas SET tipo = %s, descricao = %s, data_limite = %s
                WHERE id = %s AND cliente_id = %s
            """, (request.form.get('tipo'), request.form.get('descricao'), request.form.get('data_limite'), tarefa_id, ctx['cliente_id']))
        conn.commit()
        flash('Tarefa atualizada com sucesso!', 'success')
    except Exception as e:
        print(f"Erro editar tarefa: {e}")
        flash('Erro ao atualizar tarefa.', 'danger')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<id>/atualizar', methods=['POST'])
def atualizar_status_tarefa(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    novo_status = request.form.get('status', 'concluida')
    CRMService.alterar_status_tarefa(ctx['cliente_id'], id, novo_status)
    flash('Status atualizado!' if novo_status != 'cancelada' else 'Tarefa cancelada.', 'success' if novo_status != 'cancelada' else 'warning')
    return redirect(request.referrer or url_for('crm.listar_apoiadores'))

@crm_bp.route('/tarefas/<tarefa_id>/concluir', methods=['POST'])
def concluir_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE tarefas SET status = 'concluida' WHERE id = %s AND cliente_id = %s", (tarefa_id, ctx['cliente_id']))
        conn.commit()
        flash('Missão finalizada com sucesso! Bom trabalho.', 'success')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<id>/excluir', methods=['POST'])
def excluir_tarefa(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    CRMService.excluir_tarefa(ctx['cliente_id'], id)
    flash('Tarefa removida.', 'warning')
    return redirect(request.referrer or url_for('crm.listar_apoiadores'))

# ---- ROTAS DE PERMISSÕES E CHAT DA TAREFA ----
@crm_bp.route('/tarefas/<tarefa_id>/adicionar_membro', methods=['POST'])
def adicionar_membro_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO tarefa_membros (tarefa_id, usuario_id, papel) VALUES (%s, %s, 'admin') 
                ON CONFLICT (tarefa_id, usuario_id) DO NOTHING
            """, (tarefa_id, request.form.get('usuario_id')))
        conn.commit()
        flash('Membro adicionado com sucesso!', 'success')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/remover_membro', methods=['POST'])
def remover_membro_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM tarefa_membros WHERE tarefa_id = %s AND usuario_id = %s", 
                           (tarefa_id, request.form.get('usuario_id')))
        conn.commit()
        flash('Membro removido.', 'success')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/pedir_acesso', methods=['POST'])
def pedir_acesso_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("INSERT INTO tarefa_pedidos_acesso (tarefa_id, usuario_id, status) VALUES (%s, %s, 'pendente')", (tarefa_id, ctx['user_id']))
            cursor.execute("SELECT assessor_id FROM tarefas WHERE id = %s", (tarefa_id,))
            tarefa = cursor.fetchone()
            if tarefa and tarefa['assessor_id']:
                cursor.execute("INSERT INTO mensagens (remetente_id, destinatario_id, conteudo) VALUES (%s, %s, %s)", 
                               (ctx['user_id'], tarefa['assessor_id'], f"Solicitei acesso à Tarefa #{tarefa_id[:8]}."))
        conn.commit()
        flash('Solicitação enviada.', 'success')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/responder_pedido', methods=['POST'])
def responder_pedido_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    usuario_pedido_id, acao = request.form.get('usuario_id'), request.form.get('acao')
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if acao == 'aceitar':
                cursor.execute("UPDATE tarefa_pedidos_acesso SET status = 'aprovado' WHERE tarefa_id = %s AND usuario_id = %s", (tarefa_id, usuario_pedido_id))
                cursor.execute("INSERT INTO tarefa_membros (tarefa_id, usuario_id, papel) VALUES (%s, %s, 'admin') ON CONFLICT DO NOTHING", (tarefa_id, usuario_pedido_id))
                cursor.execute("INSERT INTO mensagens (remetente_id, destinatario_id, conteudo) VALUES (%s, %s, %s)", 
                               (ctx['user_id'], usuario_pedido_id, f"Aprovei seu acesso à Tarefa #{tarefa_id[:8]}."))
                flash('Acesso concedido.', 'success')
            else:
                cursor.execute("UPDATE tarefa_pedidos_acesso SET status = 'recusado' WHERE tarefa_id = %s AND usuario_id = %s", (tarefa_id, usuario_pedido_id))
                flash('Acesso recusado.', 'warning')
        conn.commit()
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/mensagem', methods=['POST'])
def enviar_mensagem_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conteudo = request.form.get('conteudo')
    if not conteudo: return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO tarefa_chat (tarefa_id, usuario_id, mensagem) VALUES (%s, %s, %s)", (tarefa_id, ctx['user_id'], conteudo))
        conn.commit()
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))


# ==========================================
# BLOCO 7: CHAT INTERNO (P2P)
# ==========================================

@crm_bp.route('/chat/<destinatario_id>', methods=['GET', 'POST'])
def chat(destinatario_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
        
    remetente_id = ctx['user_id']
    if remetente_id == destinatario_id:
        flash('Você não pode iniciar um chat consigo mesmo.', 'warning')
        return redirect(url_for('crm.listar_equipe'))

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # POST: Enviar
            if request.method == 'POST':
                conteudo = request.form.get('conteudo', '').strip()
                if conteudo:
                    cursor.execute("""
                        INSERT INTO mensagens (remetente_id, destinatario_id, conteudo, respondendo_a_id)
                        VALUES (%s, %s, %s, %s)
                    """, (remetente_id, destinatario_id, conteudo, request.form.get('respondendo_a_id') or None))
                    conn.commit()
                return redirect(url_for('crm.chat', destinatario_id=destinatario_id))

            # GET: Ler e Listar
            cursor.execute("SELECT id, nome, role FROM usuarios WHERE id = %s AND cliente_id = %s", (destinatario_id, ctx['cliente_id']))
            destinatario = cursor.fetchone()

            cursor.execute("""
                UPDATE mensagens SET lida = TRUE 
                WHERE destinatario_id = %s AND remetente_id = %s AND lida = FALSE
            """, (remetente_id, destinatario_id))
            conn.commit()

            cursor.execute("""
                SELECT m.*, m.data_envio AT TIME ZONE 'America/Sao_Paulo' AS data_envio_local,
                       r.conteudo AS respondendo_a_conteudo, r.remetente_id AS respondendo_a_remetente
                FROM mensagens m
                LEFT JOIN mensagens r ON m.respondendo_a_id = r.id
                WHERE (m.remetente_id = %s AND m.destinatario_id = %s)
                   OR (m.remetente_id = %s AND m.destinatario_id = %s)
                ORDER BY m.data_envio ASC
            """, (remetente_id, destinatario_id, destinatario_id, remetente_id))
            mensagens = cursor.fetchall()
            
    except Exception as e:
        print(f"Erro no chat: {e}")
        mensagens, destinatario = [], {}
    finally:
        if conn: conn.close()

    return render_template('crm/chat.html', destinatario=destinatario, mensagens=mensagens, meu_id=remetente_id)

@crm_bp.route('/chat/apagar/<mensagem_id>', methods=['POST'])
def apagar_mensagem(mensagem_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE mensagens SET apagada = TRUE WHERE id = %s AND remetente_id = %s", (mensagem_id, ctx['user_id']))
        conn.commit()
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.chat', destinatario_id=request.form.get('destinatario_id')))

@crm_bp.route('/chat/editar/<mensagem_id>', methods=['POST'])
def editar_mensagem(mensagem_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    novo_conteudo = request.form.get('novo_conteudo', '').strip()
    if novo_conteudo:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE mensagens SET conteudo = %s, editada = TRUE 
                    WHERE id = %s AND remetente_id = %s AND apagada = FALSE
                """, (novo_conteudo, mensagem_id, ctx['user_id']))
            conn.commit()
        finally:
            if conn: conn.close()
    return redirect(url_for('crm.chat', destinatario_id=request.form.get('destinatario_id')))


# ==========================================
# BLOCO 8: NOTIFICAÇÕES E ALERTAS
# ==========================================

@crm_bp.context_processor
def injetar_notificacoes():
    if 'user_id' not in session: return dict(total_notificacoes=0, msgs_nao_lidas=0, tarefas_pendentes=0)
    
    user_id = session.get('user_id')
    conn = get_db_connection()
    msgs, tarefas = 0, 0

    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM mensagens WHERE destinatario_id = %s AND lida = FALSE AND apagada = FALSE", (user_id,))
                msgs = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM tarefas WHERE assessor_id = %s AND status = 'pendente'", (user_id,))
                tarefas = cursor.fetchone()[0]
        finally:
            conn.close()
            
    return dict(total_notificacoes=(msgs + tarefas), msgs_nao_lidas=msgs, tarefas_pendentes=tarefas)

@crm_bp.route('/notificacoes', methods=['GET'])
def notificacoes():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    alertas_chat, tarefas_notificacoes = [], []
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Chat
            cursor.execute("""
                SELECT m.remetente_id, u.nome, COUNT(m.id) as qtd, MAX(m.data_envio) as ultima_msg
                FROM mensagens m JOIN usuarios u ON m.remetente_id = u.id
                WHERE m.destinatario_id = %s AND m.lida = FALSE AND m.apagada = FALSE
                GROUP BY m.remetente_id, u.nome ORDER BY ultima_msg DESC
            """, (ctx['user_id'],))
            alertas_chat = cursor.fetchall()
            
            # 2. Tarefas
            cursor.execute("SELECT id, tipo, descricao, data_limite FROM tarefas WHERE assessor_id = %s AND status = 'pendente' ORDER BY data_limite ASC", (ctx['user_id'],))
            tarefas_db = cursor.fetchall()
            
            hoje, amanha = datetime.now().date(), datetime.now().date() + timedelta(days=1)
            
            for t in tarefas_db:
                venc = _parse_date(t.get('data_limite'))
                if not venc: cor, icone, msg = 'secondary', 'fa-thumbtack', "Sem data"
                elif venc < hoje: cor, icone, msg = 'danger', 'fa-triangle-exclamation', f"Atrasada ({venc.strftime('%d/%m')})"
                elif venc == hoje: cor, icone, msg = 'primary', 'fa-calendar-day', "Vence HOJE"
                elif venc == amanha: cor, icone, msg = 'warning', 'fa-clock', "Para amanhã"
                else: cor, icone, msg = 'info', 'fa-calendar-check', f"Para dia {venc.strftime('%d/%m')}"

                tarefas_notificacoes.append({
                    'id': t['id'], 'titulo': t['tipo'] or 'Tarefa', 'descricao': t['descricao'] or '',
                    'mensagem': msg, 'cor': cor, 'icone': icone
                })
    finally:
        if conn: conn.close()
        
    return render_template('crm/notificacoes.html', alertas_chat=alertas_chat, tarefas_notificacoes=tarefas_notificacoes, permissoes=ctx['permissoes'])

@crm_bp.route('/notificacoes/limpar', methods=['POST'])
def limpar_notificacoes():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE mensagens SET lida = TRUE WHERE destinatario_id = %s AND lida = FALSE", (ctx['user_id'],))
        conn.commit()
        flash('Todas as notificações foram marcadas como lidas.', 'success')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.notificacoes'))


# ==========================================
# BLOCO 9: APIs INTERNAS (SUPORTE AO FRONT)
# ==========================================

@crm_bp.route('/api/apoiadores/busca')
def api_busca_apoiadores():
    """Endpoint para busca dinâmica via JavaScript (Autocomplete)"""
    ctx = obter_contexto_acesso()
    if not ctx: return jsonify([])
    
    termo = request.args.get('q', '')
    return jsonify(CRMService.buscar_apoiadores_por_nome(ctx['cliente_id'], termo))