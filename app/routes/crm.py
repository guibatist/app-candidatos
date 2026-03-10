# === BLOCO 1: DEPENDÊNCIAS E SETUP ===
import os
import json
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from psycopg2.extras import RealDictCursor

# Nossos módulos
from ..services.crm_service import CRMService
from app.utils.db import get_db_connection

crm_bp = Blueprint('crm', __name__)


# === BLOCO 2: HELPERS E CONTROLE DE ACESSO ===
def obter_contexto_acesso():
    """
    Recupera o contexto do usuário logado e define permissões base.
    No futuro, isso conversará com as regras do SuperAdmin.
    """
    if 'user_id' not in session:
        return None
    
    role = session.get('role')
    # Simplificamos: Se está logado, tem acesso aos módulos base no PostgreSQL
    permissoes = {
        "permite_mapa": True if role in ['candidato', 'coordenador', 'superadmin'] else False,
        "permite_equipe": True if role in ['candidato', 'coordenador', 'superadmin'] else False,
        "permite_bi": True if role in ['candidato', 'superadmin'] else False
    }
    
    return {
        "cliente_id": session.get('cliente_id'),
        "role": role,
        "permissoes": permissoes
    }


# === BLOCO 3: DASHBOARD E GEOINTELIGÊNCIA ===
@crm_bp.route('/dashboard') 
def dashboard_index():
    ctx = obter_contexto_acesso()
    if not ctx: 
        return redirect(url_for('auth.login'))
        
    resumo = CRMService.get_dashboard_data(ctx['cliente_id'])
    return render_template('crm/dashboard.html', 
                           resumo=resumo, 
                           permissoes=ctx['permissoes'])

@crm_bp.route('/mapa')
def mapa_bairros():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    if not ctx['permissoes']['permite_mapa']:
        flash('Seu perfil não tem acesso ao mapa.', 'warning')
        return redirect(url_for('crm.dashboard_index'))

    dados_mapa = CRMService.get_dados_mapa(ctx['cliente_id'])
    return render_template('crm/mapa.html', dados_mapa=dados_mapa, permissoes=ctx['permissoes'])


# === BLOCO 4: GESTÃO DE APOIADORES (CRUD E PERFIL) ===
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

    cliente_id = str(ctx['cliente_id'])
    
    # Busca o Apoiador
    apoiadores = CRMService.get_apoiadores(cliente_id)
    apoiador = next((a for a in apoiadores if str(a['id']) == str(apoiador_id)), None)

    if not apoiador:
        flash('Apoiador não encontrado.', 'danger')
        return redirect(url_for('crm.listar_apoiadores'))

    # Busca as Tarefas do Apoiador
    todas_tarefas = CRMService.listar_tarefas_apoiador(cliente_id, apoiador_id)
    pendentes = [t for t in todas_tarefas if str(t.get('status')).lower() == 'pendente']
    historico = [t for t in todas_tarefas if str(t.get('status')).lower() in ['concluida', 'cancelada']]

    # Busca os Assessores na tabela de usuários para delegação de tarefas
    assessores = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, nome FROM usuarios 
                    WHERE cliente_id = %s AND role = 'assessor'
                """, (cliente_id,))
                assessores = cursor.fetchall()
        finally:
            conn.close()

    return render_template('crm/perfil_apoiador.html', 
                           apoiador=apoiador,
                           tarefas=todas_tarefas,
                           pendentes=pendentes,
                           historico=historico,
                           todas_tarefas=todas_tarefas,
                           assessores=assessores,
                           user_role=ctx['role'],
                           permissoes=ctx['permissoes'])

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


# === BLOCO 5: GESTÃO DE TAREFAS ===
@crm_bp.route('/apoiadores/<apoiador_id>/tarefas', methods=['POST'])
def nova_tarefa(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    CRMService.adicionar_tarefa(ctx['cliente_id'], apoiador_id, request.form)
    flash('Tarefa adicionada com sucesso!', 'success')
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

@crm_bp.route('/tarefas/<id>/atualizar', methods=['POST'])
def atualizar_status_tarefa(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    novo_status = request.form.get('status', 'concluida')
    CRMService.alterar_status_tarefa(ctx['cliente_id'], id, novo_status)
    
    if novo_status == 'cancelada':
        flash('Tarefa cancelada.', 'warning')
    else:
        flash('Tarefa concluída com sucesso!', 'success')
        
    return redirect(request.referrer or url_for('crm.listar_apoiadores'))

@crm_bp.route('/tarefas/<id>/editar', methods=['POST'])
def editar_tarefa(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    CRMService.editar_tarefa(ctx['cliente_id'], id, request.form)
    flash('Tarefa atualizada com sucesso!', 'success')
    return redirect(request.referrer or url_for('crm.listar_apoiadores'))

@crm_bp.route('/tarefas/<id>/excluir', methods=['POST'])
def excluir_tarefa(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    CRMService.excluir_tarefa(ctx['cliente_id'], id)
    flash('Tarefa removida.', 'warning')
    return redirect(request.referrer or url_for('crm.listar_apoiadores'))


# === BLOCO 6: EQUIPE E ADMINISTRAÇÃO ===
@crm_bp.route('/equipe', methods=['GET'])
def minha_equipe():
    """
    Carrega a lista da equipe no CRM com base na hierarquia:
    - Se for Candidato: Vê apenas os assessores.
    - Se for Assessor: Vê o Candidato no topo + outros assessores.
    Nenhum usuário vê a si mesmo na lista.
    """
    ctx = obter_contexto_acesso()
    if not ctx: 
        return redirect(url_for('auth.login'))
        
    cliente_id = ctx['cliente_id']
    
    # CORREÇÃO AQUI: Pegamos direto da sessão do Flask para evitar o KeyError
    user_id = session.get('user_id') 
    role_logado = session.get('role') 
    
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.', 'danger')
        return redirect(url_for('crm.dashboard_index'))

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if role_logado == 'candidato':
                # REGRA 1: É candidato. Mostra apenas os assessores/coordenadores.
                cursor.execute("""
                    SELECT id, nome, email, telefone, cpf, role, status 
                    FROM usuarios 
                    WHERE cliente_id = %s AND role != 'candidato' AND id != %s
                    ORDER BY nome ASC
                """, (cliente_id, user_id))
            else:
                # REGRA 2: É assessor. Mostra o Candidato (peso 1) no topo, depois assessores (peso 2).
                cursor.execute("""
                    SELECT id, nome, email, telefone, cpf, role, status 
                    FROM usuarios 
                    WHERE cliente_id = %s AND id != %s
                    ORDER BY 
                        CASE WHEN role = 'candidato' THEN 1 ELSE 2 END,
                        nome ASC
                """, (cliente_id, user_id))
                
            equipe = cursor.fetchall()
            
    except Exception as e:
        print(f"❌ Erro ao carregar equipe no CRM: {e}")
        equipe = []
        flash('Erro técnico ao carregar a equipe.', 'danger')
    finally:
        conn.close()

    return render_template('crm/equipe.html', equipe=equipe, permissoes=ctx['permissoes'], role_logado=role_logado)

@crm_bp.route('/equipe')
def listar_equipe():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    # Busca a lista de usuários no banco filtrando por cliente_id
    equipe = CRMService.listar_equipe(ctx['cliente_id'])
    
    # O nome da variável aqui DEVE ser 'equipe' para bater com o HTML
    return render_template('crm/equipe.html', equipe=equipe)


# === BLOCO 7: FUNÇÕES DE CHAT E NOTIFICAÇÕES ===

@crm_bp.route('/chat/<destinatario_id>', methods=['GET', 'POST'])
def chat(destinatario_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
        
    remetente_id = session.get('user_id')
    
    if remetente_id == destinatario_id:
        flash('Você não pode iniciar um chat consigo mesmo.', 'warning')
        return redirect(url_for('crm.minha_equipe'))

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. ENVIANDO MENSAGEM (POST)
            if request.method == 'POST':
                conteudo = request.form.get('conteudo', '').strip()
                respondendo_a_id = request.form.get('respondendo_a_id') or None # Pega o ID da resposta
                
                if conteudo:
                    cursor.execute("""
                        INSERT INTO mensagens (remetente_id, destinatario_id, conteudo, respondendo_a_id)
                        VALUES (%s, %s, %s, %s)
                    """, (remetente_id, destinatario_id, conteudo, respondendo_a_id))
                    conn.commit()
                return redirect(url_for('crm.chat', destinatario_id=destinatario_id))

            # 2. CARREGANDO A TELA (GET)
            cursor.execute("SELECT id, nome, role FROM usuarios WHERE id = %s", (destinatario_id,))
            destinatario = cursor.fetchone()

            cursor.execute("""
                UPDATE mensagens SET lida = TRUE 
                WHERE destinatario_id = %s AND remetente_id = %s AND lida = FALSE
            """, (remetente_id, destinatario_id))
            conn.commit()

            # O PULO DO GATO: Hora do Brasil (America/Sao_Paulo) e JOIN para puxar a mensagem respondida
            cursor.execute("""
                SELECT m.*, 
                       m.data_envio AT TIME ZONE 'America/Sao_Paulo' AS data_envio_local,
                       r.conteudo AS respondendo_a_conteudo,
                       r.remetente_id AS respondendo_a_remetente
                FROM mensagens m
                LEFT JOIN mensagens r ON m.respondendo_a_id = r.id
                WHERE (m.remetente_id = %s AND m.destinatario_id = %s)
                   OR (m.remetente_id = %s AND m.destinatario_id = %s)
                ORDER BY m.data_envio ASC
            """, (remetente_id, destinatario_id, destinatario_id, remetente_id))
            mensagens = cursor.fetchall()
            
    except Exception as e:
        print(f"❌ Erro no chat: {e}")
        conn.rollback()
        mensagens = []
        destinatario = {}
    finally:
        conn.close()

    return render_template('crm/chat.html', destinatario=destinatario, mensagens=mensagens, meu_id=remetente_id)

@crm_bp.route('/chat/apagar/<mensagem_id>', methods=['POST'])
def apagar_mensagem(mensagem_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    meu_id = session.get('user_id')
    destinatario_id = request.form.get('destinatario_id') # Para saber pra onde voltar

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Soft Delete: Apenas atualiza a flag se eu for o dono da mensagem
            cursor.execute("""
                UPDATE mensagens SET apagada = TRUE 
                WHERE id = %s AND remetente_id = %s
            """, (mensagem_id, meu_id))
        conn.commit()
    except Exception as e:
        print(f"Erro ao apagar: {e}")
    finally:
        conn.close()

    return redirect(url_for('crm.chat', destinatario_id=destinatario_id))

@crm_bp.route('/chat/editar/<mensagem_id>', methods=['POST'])
def editar_mensagem(mensagem_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    meu_id = session.get('user_id')
    destinatario_id = request.form.get('destinatario_id')
    novo_conteudo = request.form.get('novo_conteudo', '').strip()

    if novo_conteudo:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Atualiza o texto e marca como editada
                cursor.execute("""
                    UPDATE mensagens SET conteudo = %s, editada = TRUE 
                    WHERE id = %s AND remetente_id = %s AND apagada = FALSE
                """, (novo_conteudo, mensagem_id, meu_id))
            conn.commit()
        except Exception as e:
            print(f"Erro ao editar: {e}")
        finally:
            conn.close()

    return redirect(url_for('crm.chat', destinatario_id=destinatario_id))

@crm_bp.context_processor
def injetar_notificacoes():
    if 'user_id' not in session:
        return dict(total_notificacoes=0, msgs_nao_lidas=0, tarefas_pendentes=0)

    user_id = session.get('user_id')
    conn = get_db_connection()
    msgs_nao_lidas = 0
    tarefas_pendentes = 0

    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # 1. Mensagens
                cursor.execute("""
                    SELECT COUNT(*) as total FROM mensagens 
                    WHERE destinatario_id = %s AND lida = FALSE AND apagada = FALSE
                """, (user_id,))
                res1 = cursor.fetchone()
                if res1: msgs_nao_lidas = res1['total']

                # 2. Tarefas Pendentes (Leitura direta e exata)
                cursor.execute("""
                    SELECT COUNT(*) as total FROM tarefas 
                    WHERE assessor_id = %s AND status = 'pendente'
                """, (user_id,))
                res2 = cursor.fetchone()
                if res2: tarefas_pendentes = res2['total']
                
        except Exception as e:
            print(f"Erro no context_processor: {e}")
        finally:
            conn.close()
            
    total = msgs_nao_lidas + tarefas_pendentes
    return dict(total_notificacoes=total, msgs_nao_lidas=msgs_nao_lidas, tarefas_pendentes=tarefas_pendentes)


@crm_bp.route('/notificacoes', methods=['GET'])
def notificacoes():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    user_id = session.get('user_id')
    conn = get_db_connection()
    alertas_chat = []
    tarefas_notificacoes = []
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Mensagens
            cursor.execute("""
                SELECT m.remetente_id, u.nome, COUNT(m.id) as qtd, MAX(m.data_envio) as ultima_msg
                FROM mensagens m
                JOIN usuarios u ON m.remetente_id = u.id
                WHERE m.destinatario_id = %s AND m.lida = FALSE AND m.apagada = FALSE
                GROUP BY m.remetente_id, u.nome
                ORDER BY ultima_msg DESC
            """, (user_id,))
            alertas_chat = cursor.fetchall()
            
            # 2. Tarefas (Leitura direta dos dados reais da sua tabela)
            cursor.execute("""
                SELECT id, tipo, descricao, data_limite
                FROM tarefas
                WHERE assessor_id = %s AND status = 'pendente'
                ORDER BY data_limite ASC
            """, (user_id,))
            tarefas_db = cursor.fetchall()
            
            from datetime import datetime, timedelta
            hoje = datetime.now().date()
            amanha = hoje + timedelta(days=1)
            
            for t in tarefas_db:
                venc = t['data_limite']
                
                # Previne erros caso a data venha como string do Postgres
                if isinstance(venc, str):
                    try:
                        venc = datetime.strptime(venc, '%Y-%m-%d').date()
                    except ValueError:
                        venc = None
                elif isinstance(venc, datetime):
                    venc = venc.date()

                titulo = t['tipo'] or 'Tarefa'
                descricao = t['descricao'] or ''
                
                if not venc:
                    cor, icone, msg = 'secondary', 'fa-thumbtack', "Sem data"
                elif venc < hoje:
                    cor, icone, msg = 'danger', 'fa-triangle-exclamation', f"Atrasada (era para {venc.strftime('%d/%m')})"
                elif venc == hoje:
                    cor, icone, msg = 'primary', 'fa-calendar-day', "Vence HOJE"
                elif venc == amanha:
                    cor, icone, msg = 'warning', 'fa-clock', "Para amanhã"
                else:
                    cor, icone, msg = 'info', 'fa-calendar-check', f"Para dia {venc.strftime('%d/%m')}"

                tarefas_notificacoes.append({
                    'id': t['id'], 
                    'titulo': titulo,
                    'descricao': descricao,
                    'mensagem': msg,
                    'cor': cor,
                    'icone': icone
                })
                    
    except Exception as e:
        print(f"Erro nas notificações: {e}")
    finally:
        if conn: conn.close()
        
    return render_template('crm/notificacoes.html', 
                           alertas_chat=alertas_chat, 
                           tarefas_notificacoes=tarefas_notificacoes,
                           permissoes=ctx['permissoes'])

@crm_bp.route('/notificacoes/limpar', methods=['POST'])
def limpar_notificacoes():
    """Marca todas as mensagens direcionadas a este utilizador como lidas."""
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    user_id = session.get('user_id')
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE mensagens SET lida = TRUE 
                WHERE destinatario_id = %s AND lida = FALSE
            """, (user_id,))
        conn.commit()
        flash('Todas as notificações foram marcadas como lidas.', 'success')
    except Exception as e:
        print(f"Erro ao limpar notificações: {e}")
        flash('Erro ao atualizar notificações.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('crm.notificacoes'))


# === BLOCO: APIs DE SUPORTE AO FRONT-END ===
@crm_bp.route('/api/apoiadores/busca')
def api_busca_apoiadores():
    """Endpoint para busca dinâmica via JavaScript (Autocomplete)"""
    ctx = obter_contexto_acesso()
    if not ctx: return jsonify([])
    
    termo = request.args.get('q', '')
    # O CRMService agora encapsula a query SQL de busca
    resultados = CRMService.buscar_apoiadores_por_nome(ctx['cliente_id'], termo)
    return jsonify(resultados)

# === BLOCO 8: GESTÃO DE TAREFAS ===
@crm_bp.route('/tarefas', methods=['GET'])
def listar_todas_tarefas():
    """Painel Global de Tarefas da Campanha (Com Paginação)."""
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    cliente_id = ctx['cliente_id']
    conn = get_db_connection()
    tarefas = []
    
    # 1. Configurações da Paginação
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    kpis = {'total': 0, 'atrasadas': 0, 'concluidas': 0}
    total_pages = 1
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 2. Atualizar Atrasadas Automaticamente
            cursor.execute("""
                UPDATE tarefas 
                SET status = 'atrasada' 
                WHERE cliente_id = %s AND status = 'pendente' 
                AND NULLIF(data_limite, '')::DATE < CURRENT_DATE
            """, (cliente_id,))
            conn.commit()

            # 3. Matemática dos KPIs Globais (Conta a base toda, não apenas a página)
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'atrasada' THEN 1 ELSE 0 END) as atrasadas,
                    SUM(CASE WHEN status IN ('concluida', 'concluído') THEN 1 ELSE 0 END) as concluidas
                FROM tarefas
                WHERE cliente_id = %s
            """, (cliente_id,))
            kpis_db = cursor.fetchone()
            
            if kpis_db:
                kpis['total'] = kpis_db['total'] or 0
                kpis['atrasadas'] = kpis_db['atrasadas'] or 0
                kpis['concluidas'] = kpis_db['concluidas'] or 0
                
            # Calcular quantas páginas existem no total
            import math
            total_pages = math.ceil(kpis['total'] / per_page) if kpis['total'] > 0 else 1

            # 4. Buscar as 10 Tarefas da Página Atual (LIMIT e OFFSET)
            cursor.execute("""
                SELECT t.id, t.tipo, t.status, t.data_limite, 
                       u.nome as delegado_nome, a.nome as apoiador_nome
                FROM tarefas t
                LEFT JOIN usuarios u ON t.assessor_id = u.id
                LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                WHERE t.cliente_id = %s
                ORDER BY 
                    CASE WHEN t.status = 'atrasada' THEN 1 WHEN t.status = 'pendente' THEN 2 ELSE 3 END,
                    NULLIF(t.data_limite, '')::DATE ASC NULLS LAST
                LIMIT %s OFFSET %s
            """, (cliente_id, per_page, offset))
            tarefas = cursor.fetchall()
            
            # 5. Tradutor de Datas para o HTML
            from datetime import datetime
            for t in tarefas:
                if t['data_limite'] and isinstance(t['data_limite'], str):
                    try:
                        t['data_limite'] = datetime.strptime(t['data_limite'], '%Y-%m-%d').date()
                    except ValueError:
                        t['data_limite'] = None
                        
    except Exception as e:
        print(f"Erro ao carregar painel de tarefas: {e}")
    finally:
        if conn: conn.close()
        
    return render_template('crm/tarefas_lista.html', 
                           tarefas=tarefas, kpis=kpis, 
                           page=page, total_pages=total_pages, 
                           permissoes=ctx['permissoes'])

@crm_bp.route('/tarefas/<tarefa_id>', methods=['GET'])
def detalhe_tarefa(tarefa_id):
    """Página de detalhes com Chat e Gestão de Acesso."""
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    user_id = session.get('user_id')
    conn = get_db_connection()
    tarefa = None
    membros = []
    mensagens_chat = []
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Carregar Dados da Tarefa
            cursor.execute("SELECT * FROM tarefas WHERE id = %s", (tarefa_id,))
            tarefa = cursor.fetchone()
            
            if not tarefa:
                flash('Tarefa não encontrada.', 'danger')
                return redirect(url_for('crm.listar_todas_tarefas'))

            # 2. Carregar Membros e Administradores
            cursor.execute("SELECT m.*, u.nome FROM tarefa_membros m JOIN usuarios u ON m.usuario_id = u.id WHERE m.tarefa_id = %s", (tarefa_id,))
            membros = cursor.fetchall()

            # 3. Carregar Chat da Tarefa
            cursor.execute("SELECT c.*, u.nome FROM tarefa_chat c JOIN usuarios u ON c.usuario_id = u.id WHERE c.tarefa_id = %s ORDER BY data_envio ASC", (tarefa_id,))
            mensagens_chat = cursor.fetchall()
            
            # 4. LÓGICA DE PERMISSÃO
            # É Dono se: assessor_id == user_id OU criador_id == user_id
            # É Admin se: está na tabela tarefa_membros como 'admin'
            is_owner = (tarefa['assessor_id'] == user_id or tarefa.get('criador_id') == user_id)
            is_admin = any(m['usuario_id'] == user_id and m['papel'] == 'admin' for m in membros)
            
            pode_editar = is_owner or is_admin

    except Exception as e:
        print(f"Erro no detalhe da tarefa: {e}")
    finally:
        if conn: conn.close()
        
    return render_template('crm/tarefa_view.html', 
                           tarefa=tarefa, 
                           membros=membros, 
                           mensagens=mensagens_chat,
                           pode_editar=pode_editar)