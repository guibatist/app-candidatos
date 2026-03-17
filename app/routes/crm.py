from datetime import datetime, timedelta
import math
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash, g, make_response
from flask_mail import Message
from psycopg2.extras import RealDictCursor
from app.routes.auth import enviar_alerta_sistema
# Nossos módulos
from ..services.crm_service import CRMService
from app.utils.db import get_db_connection
import uuid
import urllib.parse
import re
import pandas as pd
from io import BytesIO
from flask import send_file
from datetime import datetime
from app.utils.mailer import Mailer
from flask_login import login_required
crm_bp = Blueprint('crm', __name__)

# ==========================================
# RELATÓRIO DASHBOARD PRINCIPAL
# ==========================================
import pandas as pd
from io import BytesIO
from flask import send_file
from app.services.crm_service import CRMService
from app.utils.db import get_db_connection
import random

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

@crm_bp.before_app_request
def carregar_notificacoes_globais():
    if 'user_id' not in session:
        g.total_notificacoes = 0
        return

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # CONTA APENAS O QUE NÃO FOI LIDO
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(id) FROM tarefas WHERE (assessor_id = %s OR cliente_id = %s) AND lida = FALSE) +
                    (SELECT COUNT(id) FROM mensagens WHERE destinatario_id = %s AND lida = FALSE AND apagada = FALSE)
                as total
            """, (session['user_id'], session['user_id'], session['user_id']))
            
            # Forçamos o valor dentro do objeto global 'g' e na variável de template
            res = cursor.fetchone()
            g.total_notificacoes = res[0] if res else 0
    except:
        g.total_notificacoes = 0
    finally:
        if conn: conn.close()

# Context Processor para garantir que o template veja o valor de 'g'

@crm_bp.app_context_processor
def inject_sidebar_notificacoes():
    user_id = session.get('user_id')
    
    if not user_id:
        return dict(total_notificacoes=0)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. TAREFAS (Igual você já tinha)
            cursor.execute("""
                SELECT COUNT(id) FROM tarefas 
                WHERE (assessor_id = %s OR cliente_id = %s) 
                AND lida = FALSE
            """, (user_id, user_id))
            t_count = cursor.fetchone()[0] or 0
            
            # 2. MENSAGENS (Igual você já tinha)
            cursor.execute("""
                SELECT COUNT(id) FROM mensagens 
                WHERE destinatario_id = %s 
                AND lida = FALSE AND apagada = FALSE
            """, (user_id,))
            m_count = cursor.fetchone()[0] or 0

            # 3. NOVIDADE: DEMANDAS DO SITE (VotoImpacto)
            # Contamos apenas as 'Nova' que pertencem a este cliente
            cursor.execute("""
                SELECT COUNT(id) FROM demandas_site 
                WHERE cliente_id = %s AND status = 'Nova'
            """, (user_id,))
            d_count = cursor.fetchone()[0] or 0
            
            # Retorna a soma total (Tarefas + Mensagens + Demandas Site)
            return dict(total_notificacoes = t_count + m_count + d_count)
    except Exception as e:
        print(f"Erro ao injetar notificações: {e}")
        return dict(total_notificacoes=0)
    finally:
        if conn: conn.close()
# ==========================================
# BLOCO 2: DASHBOARD E GEOINTELIGÊNCIA
# ==========================================

@crm_bp.route('/dashboard')
def dashboard_index():
    # Verifica se o usuário está logado usando sua lógica de sessão
    user_id = session.get('user_id')
    cliente_id = session.get('cliente_id')
    
    if not user_id or not cliente_id:
        # Se não tiver sessão, manda pro login
        return redirect(url_for('auth.login'))

    # Agora sim, chama o serviço que tem os prints de DEBUG
    resumo = CRMService.gerar_resumo_dashboard(cliente_id)
    
    return render_template('crm/dashboard.html', resumo=resumo)

@crm_bp.route('/mapa')
def mapa_calor():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # O SEGREDO ESTÁ AQUI: 'lon as lng'
            cursor.execute("""
                SELECT 
                    id, nome, lat, lon as lng, grau_apoio, votos_familia, 
                    logradouro, numero, bairro, cidade, uf,
                    sexo, faixa_etaria 
                FROM apoiadores 
                WHERE cliente_id = %s AND lat IS NOT NULL AND lon IS NOT NULL
            """, (ctx['cliente_id'],))
            
            dados_mapa = cursor.fetchall()
            
    finally:
        if conn: conn.close()
        
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

            # 3. Resumo Tarefas (Com conversão de tipo para evitar erro 500)
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'pendente' THEN 1 ELSE 0 END) as pendentes,
                       SUM(CASE 
                           WHEN status = 'atrasada' THEN 1 
                           WHEN status = 'pendente' AND data_limite::timestamp < NOW() THEN 1 
                           ELSE 0 
                       END) as atrasadas
                FROM tarefas WHERE apoiador_id = %s
            """, (apoiador_id,))
            resumo_tarefas = cursor.fetchone()  

            # 4. Lista Tarefas (Usando 'tipo' como o título da missão)
            cursor.execute("""
                SELECT t.id, t.tipo, t.status, t.data_limite, t.descricao,
                       u.nome as assessor_nome
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
                           assessores=assessores, permissoes=ctx['permissoes'],
                           agora=datetime.now())

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
        # 1. Transforma o request.form (imutável) num dicionário editável
        dados = dict(request.form)
        
        # 2. Captura os votos da família (se vier vazio ou com erro, assume 1)
        try:
            votos = int(dados.get('votos_familia') or 1)
        except ValueError:
            votos = 1
            
        # 3. O Motor de Inteligência Eleitoral
        if votos <= 1:
            dados['grau_apoio'] = 'Simpatizante'
        elif 2 <= votos <= 4:
            dados['grau_apoio'] = 'Apoiador'
        else:
            dados['grau_apoio'] = 'Liderança'
            
        # 4. Manda para o Service já com o grau_apoio calculado e cravado
        CRMService.adicionar_apoiador(ctx['cliente_id'], dados)
        return redirect(url_for('crm.listar_apoiadores'))
        
    return render_template('crm/form_apoiador.html', permissoes=ctx['permissoes'])


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

    # --- MOTOR DE INTELIGÊNCIA AUTOMÁTICO ---
    try:
        votos = int(dados.get('votos_familia') or 1)
    except ValueError:
        votos = 1

    if votos <= 1:
        dados['grau_apoio'] = 'Simpatizante'
    elif 2 <= votos <= 4:
        dados['grau_apoio'] = 'Apoiador'
    else:
        dados['grau_apoio'] = 'Liderança'
        dados['lideranca'] = True # Força checkbox de liderança se tiver 5+ votos
    # ----------------------------------------

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE apoiadores SET 
                    nome=%(nome)s, telefone=%(telefone)s, logradouro=%(logradouro)s, 
                    numero=%(numero)s, bairro=%(bairro)s, cep=%(cep)s,
                    votos_familia=%(votos_familia)s, grau_apoio=%(grau_apoio)s,
                    lideranca=%(lideranca)s, tags=%(tags)s
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

@crm_bp.route('/apoiadores/<apoiador_id>/tarefa', methods=['POST'])
def criar_tarefa_perfil(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    tipo = request.form.get('tipo')
    assessor_id = request.form.get('assessor_id')
    data_limite = request.form.get('data_limite')
    descricao = request.form.get('descricao')
    
    # 1. Gera o ID obrigatório da tarefa
    tarefa_id = f"tar_{uuid.uuid4().hex[:10]}"
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 2. Insere no banco passando o ID
            cursor.execute("""
                INSERT INTO tarefas (id, cliente_id, apoiador_id, assessor_id, tipo, descricao, data_limite, status, lida)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendente', FALSE)
            """, (tarefa_id, ctx['cliente_id'], apoiador_id, assessor_id, tipo, descricao, data_limite))
            
            # 3. Pega os dados do assessor para enviar o e-mail
            assessor_nome = None
            assessor_email = None
            if assessor_id:
                cursor.execute("SELECT nome, email FROM usuarios WHERE id = %s", (assessor_id,))
                row = cursor.fetchone()
                if row:
                    assessor_nome, assessor_email = row[0], row[1]
                    
        conn.commit()
        
        # 4. Concatena os dados do form em uma string limpa e manda para o Mailer
        if assessor_email:
            texto_descricao = f"Você foi designado para uma nova tarefa: {tipo}. Prazo: {data_limite}."
            
            Mailer.enviar_aviso_sistema(
                email=assessor_email,
                nome_usuario=assessor_nome,
                tipo_alerta="Nova Missão Operacional",
                descricao=texto_descricao
            )
            
        flash('Missão lançada e assessor notificado!', 'success')
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Erro ao criar tarefa: {e}")
        flash('Erro ao agendar tarefa.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

# No arquivo app/routes/crm.py
@crm_bp.route('/apoiadores/<apoiador_id>/tarefas', methods=['POST'])
def nova_tarefa(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    # IMPORTANTE: O quarto parâmetro 'ctx['user_id']' deve estar presente!
    CRMService.adicionar_tarefa(ctx['cliente_id'], apoiador_id, request.form, ctx['user_id'])
    
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
            # 1. Atualiza status de atrasadas em massa (Ignorando avisos)
            cursor.execute("""
                UPDATE tarefas SET status = 'atrasada' 
                WHERE cliente_id = %s 
                AND status = 'pendente' 
                AND tipo != 'Aviso de Sistema'
                AND NULLIF(data_limite, '')::DATE < CURRENT_DATE
            """, (ctx['cliente_id'],))
            conn.commit()

            # 2. Métricas Reais (Filtramos 'Aviso de Sistema' para não poluir os KPIs)
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'atrasada' THEN 1 ELSE 0 END) as atrasadas,
                       SUM(CASE WHEN status IN ('concluida', 'concluído') THEN 1 ELSE 0 END) as concluidas
                FROM tarefas 
                WHERE cliente_id = %s 
                AND tipo != 'Aviso de Sistema'
            """, (ctx['cliente_id'],))
            kpis_db = cursor.fetchone()
            
            if kpis_db:
                # O total aqui agora reflete apenas MISSÕES reais
                kpis.update({k: v or 0 for k, v in kpis_db.items()})
                
            total_pages = math.ceil(kpis['total'] / per_page) if kpis['total'] > 0 else 1

            # 3. Busca Paginada (Filtramos para o Radar ficar limpo)
            cursor.execute("""
                SELECT t.id, t.tipo, t.status, t.data_limite, u.nome as delegado_nome, a.nome as apoiador_nome
                FROM tarefas t
                LEFT JOIN usuarios u ON t.assessor_id = u.id
                LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                WHERE t.cliente_id = %s 
                AND t.tipo != 'Aviso de Sistema'
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
            # 1. BUSCA DADOS DA TAREFA
            cursor.execute("""
                SELECT t.*, u_ass.nome as delegado_nome, u_cri.nome as criador_nome, a.nome as apoiador_nome
                FROM tarefas t
                LEFT JOIN usuarios u_ass ON t.assessor_id = u_ass.id
                LEFT JOIN usuarios u_cri ON t.criador_id = u_cri.id
                LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                WHERE t.id = %s AND t.cliente_id = %s
            """, (str(tarefa_id), ctx['cliente_id']))
            tarefa = cursor.fetchone()
            
            if not tarefa:
                flash('Tarefa não encontrada.', 'danger')
                return redirect(url_for('crm.listar_todas_tarefas'))

            # 2. REDIRECIONADOR DE NOTIFICAÇÃO ([Ref:id])
            if tarefa['tipo'] == 'Aviso de Sistema' and '[Ref:' in (tarefa['descricao'] or ''):
                match = re.search(r'\[Ref:(.+?)\]', tarefa['descricao'])
                if match:
                    real_id = match.group(1).strip()
                    
                    # Marcar como lida e também mudar o status para 'concluida' 
                    # para que ela saia do Radar de missões pendentes.
                    cursor.execute("""
                        UPDATE tarefas 
                        SET lida = TRUE, status = 'concluida' 
                        WHERE id = %s
                    """, (str(tarefa_id),))
                    conn.commit()
                    
                    # Redireciona para a tarefa real que importa
                    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=real_id))

            # 3. BUSCA DEPENDÊNCIAS
            cursor.execute("SELECT m.*, u.nome FROM tarefa_membros m JOIN usuarios u ON m.usuario_id = u.id WHERE m.tarefa_id = %s", (str(tarefa_id),))
            membros = cursor.fetchall()
            
            cursor.execute("SELECT c.*, u.nome FROM tarefa_chat c JOIN usuarios u ON c.usuario_id = u.id WHERE c.tarefa_id = %s ORDER BY data_envio ASC", (str(tarefa_id),))
            mensagens = cursor.fetchall()
            
            cursor.execute("SELECT p.*, u.nome FROM tarefa_pedidos_acesso p JOIN usuarios u ON p.usuario_id = u.id WHERE p.tarefa_id = %s AND p.status = 'pendente'", (str(tarefa_id),))
            pedidos = cursor.fetchall()

            cursor.execute("SELECT id, nome FROM usuarios WHERE cliente_id = %s ORDER BY nome", (ctx['cliente_id'],))
            usuarios_equipa = cursor.fetchall()

            # 4. REGRAS DE ACESSO (Cálculo no Python para não dar erro no HTML)
            user_id_str = str(ctx['user_id'])
            assessor_id_str = str(tarefa['assessor_id']) if tarefa['assessor_id'] else ""
            criador_id_str = str(tarefa['criador_id']) if tarefa['criador_id'] else ""
            
            # Líder = Quem manda (Pode excluir membros)
            eh_lider = (user_id_str == assessor_id_str or user_id_str == criador_id_str)
            
            # Membro = Quem está na lista de membros
            na_equipe = any(str(m['usuario_id']) == user_id_str for m in membros)
            
            # Pode Editar/Chat = Líder ou Membro
            pode_editar = eh_lider or na_equipe

    except Exception as e:
        print(f"Erro detalhe tarefa: {e}")
        flash('Erro ao carregar missão.', 'danger')
        return redirect(url_for('crm.listar_todas_tarefas'))
    finally:
        if conn: conn.close()
        
    return render_template('crm/tarefa_view.html', 
                           tarefa=tarefa, 
                           membros=membros, 
                           mensagens=mensagens, 
                           pode_editar=pode_editar, 
                           eh_lider=eh_lider,  # <--- Nova variável
                           pedidos=pedidos, 
                           usuarios_equipa=usuarios_equipa)

import uuid
from flask import request, flash, redirect, url_for, session
from psycopg2.extras import RealDictCursor

def verificar_permissao_tarefa(cursor, tarefa_id, user_id, cliente_id, exige_admin=False):
    """Retorna True se o usuário for o dono ou membro da tarefa."""
    cursor.execute("""
        SELECT t.assessor_id, t.criador_id, m.id 
        FROM tarefas t
        LEFT JOIN tarefa_membros m ON t.id = m.tarefa_id AND m.usuario_id = %s
        WHERE t.id = %s AND t.cliente_id = %s
    """, (user_id, str(tarefa_id), cliente_id))
    row = cursor.fetchone()
    if not row: return False
    
    is_owner = (row[0] == user_id or row[1] == user_id)
    is_membro = (row[2] is not None)
    
    return is_owner or is_membro # Libera total para qualquer membro

@crm_bp.route('/tarefas/<tarefa_id>/editar', methods=['POST'])
def editar_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not verificar_permissao_tarefa(cursor, tarefa_id, ctx['user_id'], ctx['cliente_id'], exige_admin=True):
                flash('Acesso negado. Apenas administradores podem editar a tarefa.', 'danger')
                return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

            cursor.execute("""
                UPDATE tarefas SET tipo = %s, descricao = %s, data_limite = %s
                WHERE id = %s AND cliente_id = %s
            """, (request.form.get('tipo'), request.form.get('descricao'), request.form.get('data_limite'), str(tarefa_id), ctx['cliente_id']))
        conn.commit()
        flash('Tarefa atualizada com sucesso!', 'success')
    except Exception as e:
        if conn: conn.rollback()
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
            if not verificar_permissao_tarefa(cursor, tarefa_id, ctx['user_id'], ctx['cliente_id'], exige_admin=False):
                flash('Acesso negado. Você não participa desta tarefa.', 'danger')
                return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

            cursor.execute("UPDATE tarefas SET status = 'concluida' WHERE id = %s AND cliente_id = %s", (str(tarefa_id), ctx['cliente_id']))
        conn.commit()
        flash('Missão finalizada com sucesso! Bom trabalho.', 'success')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/solicitar-acesso', methods=['POST'])
def solicitar_acesso_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Registra o Pedido
            cursor.execute("INSERT INTO tarefa_pedidos_acesso (tarefa_id, usuario_id, status) VALUES (%s, %s, 'pendente') ON CONFLICT DO NOTHING", (str(tarefa_id), ctx['user_id']))
            # 2. Notifica o Responsável
            cursor.execute("SELECT assessor_id, tipo FROM tarefas WHERE id = %s", (str(tarefa_id),))
            t = cursor.fetchone()
            if t:
                id_notif = str(uuid.uuid4())
                msg = f"{session.get('nome')} solicitou acesso à tarefa '{t['tipo']}'. [Ref:{tarefa_id}]"
                cursor.execute("INSERT INTO tarefas (id, cliente_id, assessor_id, tipo, descricao, status, lida) VALUES (%s, %s, %s, 'Aviso de Sistema', %s, 'pendente', FALSE)", (id_notif, ctx['cliente_id'], t['assessor_id'], msg))
            conn.commit()
            flash('Solicitação enviada!', 'success')
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))


# ---- ROTAS DE PERMISSÕES E EQUIPE DA TAREFA ----
@crm_bp.route('/tarefas/<tarefa_id>/membros/adicionar', methods=['POST'])
def adicionar_membro_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    novo_membro_id = request.form.get('usuario_id')
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Verifica se a tarefa não está concluída
            cursor.execute("SELECT status, tipo FROM tarefas WHERE id = %s", (str(tarefa_id),))
            tarefa_meta = cursor.fetchone()
            if tarefa_meta['status'] == 'concluida':
                flash('Não é possível adicionar membros a uma tarefa concluída.', 'warning')
                return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

            # 2. Adiciona na tabela de membros
            cursor.execute("""
                INSERT INTO tarefa_membros (tarefa_id, usuario_id, papel) 
                VALUES (%s, %s, 'membro') ON CONFLICT DO NOTHING
            """, (str(tarefa_id), str(novo_membro_id)))
            
            # 3. GERA A NOTIFICAÇÃO COM O LINK (REF) PARA O CONVIDADO
            id_notif = str(uuid.uuid4())
            # AQUI ESTÁ O LINK: [Ref:tarefa_id]
            msg = f"Você foi adicionado à equipe da missão: '{tarefa_meta['tipo']}'. [Ref:{tarefa_id}]"
            
            cursor.execute("""
                INSERT INTO tarefas (id, cliente_id, assessor_id, tipo, descricao, status, lida) 
                VALUES (%s, %s, %s, 'Aviso de Sistema', %s, 'pendente', FALSE)
            """, (id_notif, ctx['cliente_id'], str(novo_membro_id), msg))
            
        conn.commit()
        flash('Membro adicionado e notificado!', 'success')
    except Exception as e:
        if conn: conn.rollback()
        print(f"Erro ao convidar: {e}")
        flash('Erro ao convidar membro.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/remover_membro', methods=['POST'])
def remover_membro_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    usuario_a_remover = request.form.get('usuario_id')
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # BUSCA QUEM É O DONO E O COORDENADOR
            cursor.execute("SELECT assessor_id, criador_id FROM tarefas WHERE id = %s", (str(tarefa_id),))
            tarefa = cursor.fetchone()
            
            if not tarefa:
                return redirect(url_for('crm.listar_todas_tarefas'))

            # TRAVA DE SEGURANÇA: Só o Criador ou o Coordenador podem remover membros
            # O Membro comum não pode se remover nem remover os outros
            pode_gerenciar_equipe = (str(ctx['user_id']) == str(tarefa['assessor_id']) or 
                                     str(ctx['user_id']) == str(tarefa['criador_id']))
            
            if not pode_gerenciar_equipe:
                flash('Acesso negado. Apenas o coordenador ou criador podem remover membros.', 'danger')
                return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

            # EXECUTA A REMOÇÃO
            cursor.execute("DELETE FROM tarefa_membros WHERE tarefa_id = %s AND usuario_id = %s", 
                           (str(tarefa_id), str(usuario_a_remover)))
            conn.commit()
            flash('Membro removido da equipe.', 'info')
            
    finally:
        if conn: conn.close()
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/pedidos/<usuario_id>/<acao>', methods=['POST'])
def responder_pedido_acesso(tarefa_id, usuario_id, acao):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT tipo, assessor_id FROM tarefas WHERE id = %s", (str(tarefa_id),))
            tarefa_info = cursor.fetchone()
            
            if not tarefa_info:
                flash('Tarefa não encontrada.', 'danger')
                return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))
                
            nome_tarefa = tarefa_info[0]

            if acao == 'aprovar':
                cursor.execute("UPDATE tarefa_pedidos_acesso SET status = 'aprovado' WHERE tarefa_id = %s AND usuario_id = %s", (str(tarefa_id), str(usuario_id)))
                cursor.execute("INSERT INTO tarefa_membros (tarefa_id, usuario_id, papel) VALUES (%s, %s, 'membro') ON CONFLICT DO NOTHING", (str(tarefa_id), str(usuario_id)))
                
                # Notifica o usuário aprovado COM UUID
                id_notif = str(uuid.uuid4())
                msg = f"Seu pedido de acesso para a tarefa '{nome_tarefa}' foi APROVADO. [Ref:{tarefa_id}]"
                cursor.execute("INSERT INTO tarefas (id, cliente_id, assessor_id, tipo, descricao, status, lida) VALUES (%s, %s, %s, 'Aviso de Sistema', %s, 'pendente', FALSE)", (id_notif, ctx['cliente_id'], str(usuario_id), msg))
                flash('Acesso aprovado e usuário notificado!', 'success')
                
            elif acao == 'recusar':
                cursor.execute("UPDATE tarefa_pedidos_acesso SET status = 'recusado' WHERE tarefa_id = %s AND usuario_id = %s", (str(tarefa_id), str(usuario_id)))
                
                # Notifica o usuário recusado COM UUID
                id_notif = str(uuid.uuid4())
                msg = f"Seu pedido de acesso para a tarefa '{nome_tarefa}' foi RECUSADO. [Ref:{tarefa_id}]"
                cursor.execute("INSERT INTO tarefas (id, cliente_id, assessor_id, tipo, descricao, status, lida) VALUES (%s, %s, %s, 'Aviso de Sistema', %s, 'pendente', FALSE)", (id_notif, ctx['cliente_id'], str(usuario_id), msg))
                flash('Acesso recusado.', 'info')
                
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"Erro ao responder pedido: {e}")
        flash('Erro ao responder pedido.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

@crm_bp.route('/tarefas/<tarefa_id>/mensagem', methods=['POST'])
def enviar_mensagem_tarefa(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conteudo = request.form.get('conteudo')
    if not conteudo:
        return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Trava de segurança
            if not verificar_permissao_tarefa(cursor, tarefa_id, ctx['user_id'], ctx['cliente_id']):
                flash('Sem permissão.', 'danger')
                return redirect(url_for('crm.detalhe_tarefa', tarefa_id=tarefa_id))

            # --- CORREÇÃO AQUI: UUID PURO ---
            id_msg = str(uuid.uuid4()) # Removido o prefixo 'msg_'
            
            cursor.execute("""
                INSERT INTO tarefa_chat (id, tarefa_id, usuario_id, mensagem, data_envio)
                VALUES (%s, %s, %s, %s, %s)
            """, (id_msg, str(tarefa_id), ctx['user_id'], conteudo, datetime.now()))
            
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"Erro ao enviar mensagem: {e}")
        flash('Erro ao enviar mensagem.', 'danger')
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
            # 1. Chat (Mantém igual, já filtra por lida=FALSE)
            cursor.execute("""
                SELECT m.remetente_id, u.nome, COUNT(m.id) as qtd, MAX(m.data_envio) as ultima_msg
                FROM mensagens m JOIN usuarios u ON m.remetente_id = u.id
                WHERE m.destinatario_id = %s AND m.lida = FALSE AND m.apagada = FALSE
                GROUP BY m.remetente_id, u.nome ORDER BY ultima_msg DESC
            """, (ctx['user_id'],))
            alertas_chat = cursor.fetchall()
            
            # 2. Tarefas - ADICIONADO FILTRO: AND lida = FALSE
            # Note que removi o status='pendente' para que o usuário possa "dar lido" 
            # mesmo em tarefas que ele ainda não concluiu, se você preferir assim.
            cursor.execute("""
                SELECT id, tipo, descricao, data_limite 
                FROM tarefas 
                WHERE assessor_id = %s AND lida = FALSE 
                ORDER BY data_limite ASC
            """, (ctx['user_id'],))
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
                    'id': t['id'], 
                    'titulo': t['tipo'] or 'Tarefa', 
                    'descricao': t['descricao'] or '',
                    'mensagem': msg, 
                    'cor': cor, 
                    'icone': icone
                })
    finally:
        if conn: conn.close()
        
    # Calculando total para o badge da interface
    total_nao_lidas = len(alertas_chat) + len(tarefas_notificacoes)
        
    return render_template('crm/notificacoes.html', 
                           alertas_chat=alertas_chat, 
                           tarefas_notificacoes=tarefas_notificacoes, 
                           total_notificacoes=total_nao_lidas, 
                           permissoes=ctx['permissoes'])

@crm_bp.route('/notificacoes/limpar', methods=['POST'])
def limpar_notificacoes():
    ctx = obter_contexto_acesso()
    if not ctx: return jsonify({'success': False}), 401
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # MARCAR TAREFAS COMO LIDAS
            cursor.execute("UPDATE tarefas SET lida = TRUE WHERE assessor_id = %s", (ctx['user_id'],))
            
            # MARCAR MENSAGENS COMO LIDAS (Opcional, mas recomendado para zerar tudo)
            cursor.execute("UPDATE mensagens SET lida = TRUE WHERE destinatario_id = %s", (ctx['user_id'],))
            
        conn.commit() # <--- OBRIGATÓRIO PARA GRAVAR NO POSTGRES
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@crm_bp.route('/tarefas/marcar-lida/<tarefa_id>', methods=['POST']) # Removi o 'int:' para aceitar UUID ou String
def marcar_tarefa_lida(tarefa_id):
    ctx = obter_contexto_acesso()
    if not ctx: 
        return jsonify({'success': False, 'error': 'Sessão expirada'}), 401
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Fazemos o update garantindo que a tarefa pertence ao usuário logado
            cursor.execute("""
                UPDATE tarefas 
                SET lida = TRUE 
                WHERE id = %s AND assessor_id = %s
            """, (str(tarefa_id), ctx['user_id']))
            
            # Verifica se alguma linha foi realmente afetada
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': 'Tarefa não encontrada'}), 404
                
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn: conn.close()

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

# ==========================================
# BLOCO 10: SUPORTE E CHAMADOS (OFFCANVAS)
# ==========================================
import os
from app.routes.auth import disparar_email_assincrono 

@crm_bp.context_processor
def injetar_historico_chamados():
    """Injeta os chamados do usuário logado na sessão para popular a aba deslizante lateral."""
    if 'user_id' not in session or session.get('role') == 'superadmin':
        return dict(meus_chamados=[])
    
    conn = get_db_connection()
    chamados = []
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM chamados_suporte 
                    WHERE usuario_id = %s ORDER BY criado_em DESC
                """, (session['user_id'],))
                chamados = cursor.fetchall()
        finally:
            conn.close()
    return dict(meus_chamados=chamados)

@crm_bp.route('/suporte/abrir', methods=['POST'])
def abrir_chamado():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    tipo_chamado = request.form.get('tipo_chamado')
    descricao = request.form.get('descricao')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO chamados_suporte (cliente_id, usuario_id, tipo, descricao, status)
                VALUES (%s, %s, %s, %s, 'Aberto') RETURNING id
            """, (ctx['cliente_id'], ctx['user_id'], tipo_chamado, descricao))
            chamado_id = cursor.fetchone()['id']
        conn.commit()

        # Usa dinamicamente o e-mail do seu .env
        email_master = os.getenv('SMTP_USER') 
        nome_usuario = session.get('nome', 'Usuário')
        
        corpo_email = f"""
        <div style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #ef4444;">🚨 Novo Chamado: #{chamado_id}</h2>
            <p>O usuário <strong>{nome_usuario}</strong> abriu uma nova solicitação.</p>
            <div style="background-color: #f3f4f6; padding: 15px; border-radius: 5px; margin: 10px 0;">
                <p><strong>Tipo:</strong> {tipo_chamado}</p>
                <p><strong>Descrição:</strong><br>{descricao}</p>
            </div>
            <p>Acesse a Central de Chamados no SuperAdmin para responder.</p>
        </div>
        """
        if email_master:
            disparar_email_assincrono(email_master, f"Suporte VotaHub: {tipo_chamado}", corpo_email)
        
        flash('Chamado enviado com sucesso! Acompanhe o status na sua aba de suporte.', 'success')
    except Exception as e:
        print(f"Erro ao abrir chamado: {e}")
        flash('Erro interno ao processar o chamado. Tente novamente.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(request.referrer or url_for('crm.dashboard_index'))

# ==========================================
# GESTÃO DE PERFIL DO USUÁRIO
# ==========================================
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

@crm_bp.route('/meu-perfil', methods=['GET', 'POST'])
def meu_perfil():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    conn = get_db_connection()
    
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        telefone = request.form.get('telefone', '').strip()
        cpf = request.form.get('cpf', '').strip()
        nova_senha = request.form.get('nova_senha')
        confirmar_senha = request.form.get('confirmar_senha')
        
        try:
            with conn.cursor() as cursor:
                # 1. Atualiza dados básicos
                cursor.execute("""
                    UPDATE usuarios 
                    SET nome = %s, telefone = %s, cpf = %s 
                    WHERE id = %s
                """, (nome, telefone, cpf, session['user_id']))
                
                # 2. Atualiza senha (se o usuário preencheu)
                if nova_senha:
                    if nova_senha == confirmar_senha and len(nova_senha) >= 8:
                        senha_hash = generate_password_hash(nova_senha)
                        cursor.execute("UPDATE usuarios SET senha_hash = %s WHERE id = %s", (senha_hash, session['user_id']))
                        flash('Senha atualizada com sucesso!', 'success')
                    else:
                        flash('As senhas não coincidem ou a senha é muito curta (mínimo 8 caracteres).', 'warning')

                conn.commit()
                # Atualiza o nome na sessão para refletir imediatamente na UI
                session['nome'] = nome 
                flash('Perfil atualizado com sucesso.', 'success')
                
        except Exception as e:
            conn.rollback()
            print(f"[DB-ERROR] Erro ao atualizar perfil: {e}")
            flash('Erro ao salvar as alterações.', 'danger')
        finally:
            if conn: conn.close()
            
        return redirect(url_for('auth.meu_perfil'))

    # Método GET: Carrega a página
    usuario = {}
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM usuarios WHERE id = %s", (session['user_id'],))
                usuario = cursor.fetchone()
        finally:
            conn.close()

    # Pode renderizar na pasta 'auth' ou 'crm', ajuste conforme sua estrutura
    return render_template('crm/perfil.html', usuario=usuario)

from flask import jsonify
    
# ==========================================
# BLOCO DE INTELIGÊNCIA E RELATÓRIOS
# ==========================================

@crm_bp.route('/relatorios')
def painel_relatorios():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Puxa a equipe para o filtro de tarefas
            cursor.execute("SELECT id, nome FROM usuarios WHERE cliente_id = %s ORDER BY nome", (ctx['cliente_id'],))
            assessores = cursor.fetchall()
            
            # Puxa os bairros dinamicamente da base para o filtro
            cursor.execute("SELECT DISTINCT bairro FROM apoiadores WHERE cliente_id = %s AND bairro IS NOT NULL AND bairro != '' ORDER BY bairro", (ctx['cliente_id'],))
            bairros = [r['bairro'] for r in cursor.fetchall()]
    finally:
        if conn: conn.close()
        
    return render_template('crm/relatorios.html', assessores=assessores, bairros=bairros, permissoes=ctx['permissoes'])

@crm_bp.route('/relatorios/exportar', methods=['POST'])
def exportar_relatorio():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    tipo_relatorio = request.form.get('tipo_relatorio')
    conn = get_db_connection()
    df = pd.DataFrame() # Cria uma tabela vazia inicial
    
    nome_arquivo = f"VotaHub_Relatorio_{datetime.now().strftime('%d%m%Y_%H%M')}.xlsx"
    
    try:
        # ---------------------------------------------------------
        # OPÇÃO A: RELATÓRIO DE APOIADORES (BASE)
        # ---------------------------------------------------------
        if tipo_relatorio == 'apoiadores':
            query = """
                SELECT nome as "Nome Completo", telefone as "WhatsApp", sexo as "Sexo", 
                       faixa_etaria as "Idade", grau_apoio as "Engajamento", 
                       votos_familia as "Potencial Votos", bairro as "Bairro", 
                       logradouro as "Rua", numero as "Número"
                FROM apoiadores 
                WHERE cliente_id = %(cliente_id)s
            """
            params = {'cliente_id': ctx['cliente_id']}
            
            # Aplica os filtros apenas se o usuário selecionou algo
            if request.form.get('grau_apoio'):
                query += " AND grau_apoio = %(grau_apoio)s"
                params['grau_apoio'] = request.form.get('grau_apoio')
            if request.form.get('sexo'):
                query += " AND sexo = %(sexo)s"
                params['sexo'] = request.form.get('sexo')
            if request.form.get('faixa_etaria'):
                query += " AND faixa_etaria = %(faixa_etaria)s"
                params['faixa_etaria'] = request.form.get('faixa_etaria')
            if request.form.get('bairro'):
                query += " AND bairro = %(bairro)s"
                params['bairro'] = request.form.get('bairro')
            
            query += " ORDER BY nome"
            df = pd.read_sql_query(query, conn, params=params)

        # ---------------------------------------------------------
        # OPÇÃO B: RELATÓRIO DE MISSÕES (TAREFAS DA EQUIPE)
        # ---------------------------------------------------------
        elif tipo_relatorio == 'tarefas':
            query = """
                SELECT t.tipo as "Missão", t.descricao as "Instruções",
                       a.nome as "Alvo (Apoiador)", a.telefone as "WhatsApp Alvo", a.bairro as "Bairro Alvo",
                       u.nome as "Assessor Responsável", t.status as "Status", t.data_limite as "Prazo"
                FROM tarefas t
                LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                LEFT JOIN usuarios u ON t.assessor_id = u.id
                WHERE t.cliente_id = %(cliente_id)s
            """
            params = {'cliente_id': ctx['cliente_id']}
            
            if request.form.get('status_tarefa'):
                query += " AND t.status = %(status)s"
                params['status'] = request.form.get('status_tarefa')
            if request.form.get('assessor_id'):
                query += " AND t.assessor_id = %(assessor_id)s"
                params['assessor_id'] = request.form.get('assessor_id')

            query += " ORDER BY t.data_limite ASC NULLS LAST"
            df = pd.read_sql_query(query, conn, params=params)

    finally:
        conn.close()

    # Se a tabela estiver vazia (ninguém atendeu aos filtros)
    if df.empty:
        flash('Nenhum registro encontrado para essa combinação de filtros.', 'warning')
        return redirect(url_for('crm.painel_relatorios'))

    # Se tiver dados, a mágica do Pandas cria o Excel lindão na memória
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Tatico')
        
        # Ajustar a largura das colunas automaticamente
        worksheet = writer.sheets['Tatico']
        for col in worksheet.columns:
            max_length = max((len(str(cell.value)) for cell in col if cell.value is not None), default=0)
            adjusted_width = min(max_length + 2, 50) # Trava o tamanho máximo em 50 para textos longos
            worksheet.column_dimensions[col[0].column_letter].width = adjusted_width

    output.seek(0)
    
    # Cospe o arquivo direto pro navegador do usuário
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=nome_arquivo
    )

@crm_bp.route('/relatorios/preview', methods=['POST'])
def preview_relatorio():
    ctx = obter_contexto_acesso()
    if not ctx: return jsonify({'error': 'Não autorizado'}), 401
    
    tipo_relatorio = request.form.get('tipo_relatorio')
    conn = get_db_connection()
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if tipo_relatorio == 'apoiadores':
                base_query = "FROM apoiadores WHERE cliente_id = %(cliente_id)s"
                params = {'cliente_id': ctx['cliente_id']}
                
                # Montando os filtros
                if request.form.get('grau_apoio'):
                    base_query += " AND grau_apoio = %(grau_apoio)s"; params['grau_apoio'] = request.form.get('grau_apoio')
                if request.form.get('sexo'):
                    base_query += " AND sexo = %(sexo)s"; params['sexo'] = request.form.get('sexo')
                if request.form.get('faixa_etaria'):
                    base_query += " AND faixa_etaria = %(faixa_etaria)s"; params['faixa_etaria'] = request.form.get('faixa_etaria')
                if request.form.get('bairro'):
                    base_query += " AND bairro = %(bairro)s"; params['bairro'] = request.form.get('bairro')
                    
                # 1. Conta o total exato
                cursor.execute(f"SELECT COUNT(*) as total {base_query}", params)
                total = cursor.fetchone()['total']
                
                # 2. Pega só os 15 primeiros para mostrar na tela (rápido!)
                cursor.execute(f"SELECT nome, telefone, bairro, grau_apoio {base_query} ORDER BY nome LIMIT 15", params)
                rows = cursor.fetchall()
                colunas = ["Nome Completo", "WhatsApp", "Bairro", "Grau de Apoio"]
                
            elif tipo_relatorio == 'tarefas':
                base_query = """
                    FROM tarefas t
                    LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                    LEFT JOIN usuarios u ON t.assessor_id = u.id
                    WHERE t.cliente_id = %(cliente_id)s
                """
                params = {'cliente_id': ctx['cliente_id']}
                
                if request.form.get('status_tarefa'):
                    base_query += " AND t.status = %(status)s"; params['status'] = request.form.get('status_tarefa')
                if request.form.get('assessor_id'):
                    base_query += " AND t.assessor_id = %(assessor_id)s"; params['assessor_id'] = request.form.get('assessor_id')
                    
                cursor.execute(f"SELECT COUNT(*) as total {base_query}", params)
                total = cursor.fetchone()['total']
                
                cursor.execute(f"SELECT t.tipo, u.nome as assessor, a.nome as apoiador, t.status {base_query} ORDER BY t.data_limite DESC NULLS LAST LIMIT 15", params)
                rows = cursor.fetchall()
                colunas = ["Missão", "Assessor Responsável", "Alvo (Apoiador)", "Status"]
            
            # Formata os dados para o Javascript ler
            linhas = [[r[list(r.keys())[0]], r[list(r.keys())[1]], r[list(r.keys())[2]], r[list(r.keys())[3]]] for r in rows] if rows else []
            
            return jsonify({
                'total': total,
                'colunas': colunas,
                'linhas': linhas
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn: conn.close()

# MODELO
# No final do seu arquivo app/routes/crm.py

@crm_bp.route('/campanha')
def landing_page_campanha():
    # Esta página é pública, então não precisa do 'obter_contexto_acesso'
    return render_template('site/landing_page.html')

@crm_bp.route('/api/site/receber-demanda', methods=['POST'])
def receber_demanda_site():
    # DEBUG: Isso vai mostrar no seu terminal o que o HTML está enviando de verdade
    print(f"--- DADOS RECEBIDOS DO SITE: {request.form.to_dict()} ---")

    token_recebido = request.form.get('api_token')
    if not token_recebido:
        return jsonify(success=False, error="Token ausente."), 400

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id, nome_candidato FROM clientes WHERE api_token = %s", (token_recebido,))
            cliente = cursor.fetchone()
            if not cliente: return jsonify(success=False, error="Token inválido."), 401
            
            cliente_id = cliente['id']
            nome_cand = cliente['nome_candidato']

            # CAPTURA INTELIGENTE (Tenta vários nomes comuns de formulário)
            nome = request.form.get('nome', '').strip()
            email = request.form.get('email', '').strip()
            tel_solicitante = request.form.get('telefone', '').strip()
            
            # Tenta 'titulo', 'assunto' ou 'subject'
            titulo = request.form.get('titulo') or request.form.get('assunto') or "Nova Demanda"
            
            # Tenta 'mensagem', 'descricao', 'message' ou 'corpo'
            descricao = request.form.get('mensagem') or request.form.get('descricao') or request.form.get('message', '').strip()

            # INSERT NO BANCO
            cursor.execute("""
                INSERT INTO demandas_site 
                (cliente_id, nome_solicitante, email_solicitante, telefone_solicitante, titulo, descricao, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'Nova')
            """, (cliente_id, nome, email, tel_solicitante, titulo, descricao))
            
            # BUSCA TELEFONE PARA WHATSAPP
            cursor.execute("SELECT telefone FROM usuarios WHERE cliente_id = %s AND role = 'assessor' AND telefone != '' LIMIT 1", (cliente_id,))
            dest = cursor.fetchone()
            if not dest:
                cursor.execute("SELECT telefone FROM usuarios WHERE cliente_id = %s AND telefone != '' LIMIT 1", (cliente_id,))
                dest = cursor.fetchone()

            link_wa = None
            if dest and dest['telefone']:
                num = re.sub(r'\D', '', str(dest['telefone']))
                if not num.startswith('55'): num = '55' + num
                
                # A MENSAGEM DO ZAP: Agora usando a descricao capturada
                texto_wa = (
                    f"🚨 *DEMANDA URGENTE* 🚨\n\n"
                    f"Olá, *{nome_cand}*, você recebeu uma nova demanda via site.\n\n"
                    f"*Resumo:* {descricao}"
                )
                link_wa = f"https://wa.me/{num}?text={urllib.parse.quote(texto_wa)}"

        conn.commit()
        return jsonify(success=True, message="Demanda registrada!", whatsapp_url=link_wa), 201
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"[DB-ERROR]: {e}")
        return jsonify(success=False, error="Erro interno."), 500
    finally:
        if conn: conn.close()


@crm_bp.route('/comunicacao')
def caixa_entrada():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Selecionamos as colunas originais para bater com o template
            cursor.execute("""
                SELECT id, nome_solicitante, email_solicitante, telefone_solicitante, 
                       titulo, descricao, status, data_recebimento 
                FROM demandas_site 
                WHERE cliente_id = %s 
                ORDER BY data_recebimento DESC
            """, (ctx['cliente_id'],))
            
            demandas = cursor.fetchall()
            
            resumo = {
                'total': len(demandas),
                'novas': sum(1 for d in demandas if d['status'] in ['Nova', 'pendente']),
                'resolvidas': sum(1 for d in demandas if d['status'] == 'Resolvida')
            }
            
    finally:
        if conn: conn.close()
        
    return render_template('crm/comunicacao.html', 
                           demandas=demandas, 
                           resumo=resumo, 
                           permissoes=ctx['permissoes'])

@crm_bp.route('/comunicacao/concluir/<int:demanda_id>', methods=['POST'])
def concluir_demanda(demanda_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE demandas_site 
                SET status = 'Resolvida' 
                WHERE id = %s
            """, (demanda_id,))
            conn.commit()
            
        flash('Demanda marcada como concluída com sucesso!', 'success')
    except Exception as e:
        print(f"Erro ao concluir demanda: {e}")
        flash('Erro ao atualizar o status da demanda.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('crm.caixa_entrada'))

@crm_bp.route('/api/notificacoes/contagem')
def contagem_notificacoes():
    # Usamos o contexto para pegar o ID da CAMPANHA (cliente_id)
    ctx = obter_contexto_acesso()
    if not ctx:
        return jsonify({'count': 0, 'status': 'sessao_expirada'}), 401

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # AQUI: Mudamos para buscar pelo cliente_id do contexto
            query = """
                SELECT COUNT(*) as total 
                FROM demandas_site 
                WHERE status = 'Nova' 
                AND cliente_id = %s
            """
            cursor.execute(query, (ctx['cliente_id'],))
            resultado = cursor.fetchone()
            
            total = resultado['total'] if resultado else 0
            
            return jsonify({
                'count': total,
                'status': 'sucesso',
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
    except Exception as e:
        print(f"🚨 [ERRO RADAR]: {e}")
        return jsonify({'count': 0, 'status': 'erro_interno'}), 500
    finally:
        if conn: conn.close()

@crm_bp.route('/api/notificacoes/radar')
def radar_notificacoes():
    ctx = obter_contexto_acesso()
    if not ctx:
        return jsonify({'total': 0}), 401

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Demandas do Site (Usa o ID da Campanha)
            cursor.execute("SELECT COUNT(id) FROM demandas_site WHERE cliente_id = %s AND status = 'Nova'", (ctx['cliente_id'],))
            d = cursor.fetchone()[0] or 0
            
            # 2. Mensagens Internas (Aqui sim usa o user_id, pois a mensagem é para a PESSOA)
            cursor.execute("SELECT COUNT(id) FROM mensagens WHERE destinatario_id = %s AND lida = FALSE", (ctx['user_id'],))
            m = cursor.fetchone()[0] or 0
            
            # 3. Tarefas (Usa o ID do usuário que deve fazer a tarefa)
            cursor.execute("SELECT COUNT(id) FROM tarefas WHERE assessor_id = %s AND lida = FALSE", (ctx['user_id'],))
            t = cursor.fetchone()[0] or 0

            return jsonify({'total': d + m + t})
    except Exception as e:
        print(f"🚨 [ERRO RADAR DETALHADO]: {e}")
        return jsonify({'total': 0})
    finally:
        conn.close()

@crm_bp.route('/dashboard/exportar-bi')
def exportar_relatorio_bi():
    cliente_id = session.get('cliente_id')
    if not cliente_id:
        return redirect(url_for('auth.login'))

    from app.services.crm_service import CRMService
    from app.utils.db import get_db_connection
    
    # Puxa os KPIs (Total e Potencial de Votos)
    resumo = CRMService.gerar_resumo_dashboard(cliente_id)
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cursor:
            # 1. Nome do Candidato (Coluna: nome_candidato)
            cursor.execute("SELECT nome_candidato FROM clientes WHERE id = %s", (cliente_id,))
            res_nome = cursor.fetchone()
            nome_candidato = res_nome[0] if res_nome else "Candidato"

            # 2. Dados de Bairros (Densidade Geográfica)
            cursor.execute("""
                SELECT bairro, COUNT(*) as qtd 
                FROM apoiadores 
                WHERE cliente_id = %s AND bairro IS NOT NULL AND bairro != '' 
                GROUP BY bairro ORDER BY qtd DESC
            """, (cliente_id,))
            df_bairros = pd.DataFrame(cursor.fetchall(), columns=["Bairro", "Total"])

            # 3. Dados de Tarefas (Status - O B.I. de Missões)
            cursor.execute("""
                SELECT status, COUNT(*) as qtd 
                FROM tarefas 
                WHERE cliente_id = %s 
                GROUP BY status
            """, (cliente_id,))
            df_tarefas_status = pd.DataFrame(cursor.fetchall(), columns=["Status", "Qtd"])

            # 4. Dados de Demografia (Sexo)
            cursor.execute("""
                SELECT sexo, COUNT(*) as qtd 
                FROM apoiadores 
                WHERE cliente_id = %s AND sexo IS NOT NULL AND sexo != '' 
                GROUP BY sexo
            """, (cliente_id,))
            df_sexo = pd.DataFrame(cursor.fetchall(), columns=["Sexo", "Total"])

            # 5. Dados de Demografia (Faixa Etária)
            cursor.execute("""
                SELECT faixa_etaria, COUNT(*) as qtd 
                FROM apoiadores 
                WHERE cliente_id = %s AND faixa_etaria IS NOT NULL AND faixa_etaria != '' 
                GROUP BY faixa_etaria ORDER BY faixa_etaria
            """, (cliente_id,))
            df_idade = pd.DataFrame(cursor.fetchall(), columns=["Faixa Etária", "Total"])

    finally:
        conn.close()

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    workbook = writer.book

    # --- ABA 1: DASHBOARD (A PRIMEIRA PAGINA) ---
    dashboard = workbook.add_worksheet('📊 B.I. ESTRATÉGICO')
    dashboard.activate()
    dashboard.set_column('A:Z', 20)

    # --- DEMAIS ABAS: DADOS BASE ---
    df_bairros.to_excel(writer, sheet_name='DB_Bairros', index=False)
    df_tarefas_status.to_excel(writer, sheet_name='DB_Tarefas', index=False)
    df_sexo.to_excel(writer, sheet_name='DB_Sexo', index=False)
    df_idade.to_excel(writer, sheet_name='DB_Idade', index=False)

    # Estilos
    fmt_header = workbook.add_format({'bold': True, 'font_size': 18, 'font_color': 'white', 'bg_color': '#4F46E5', 'align': 'center', 'valign': 'vcenter'})
    fmt_kpi_label = workbook.add_format({'bold': True, 'bg_color': '#F1F5F9', 'border': 1, 'align': 'center'})
    fmt_kpi_val = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'border': 1, 'font_color': '#4F46E5'})

    # Título e Cards de KPI
    dashboard.merge_range('B2:J3', f'RELATÓRIO DE INTELIGÊNCIA: {nome_candidato.upper()}', fmt_header)
    dashboard.write('B5', 'TOTAL APOIADORES', fmt_kpi_label)
    dashboard.write('B6', resumo['kpis'].get('total', 0), fmt_kpi_val)
    dashboard.write('D5', 'POTENCIAL VOTOS', fmt_kpi_label)
    dashboard.write('D6', resumo['kpis'].get('potencial_votos', 0), fmt_kpi_val)

    # GRÁFICO 1: MISSÕES (PIZZA)
    if not df_tarefas_status.empty:
        c1 = workbook.add_chart({'type': 'pie'})
        c1.add_series({
            'name': 'Status das Missões',
            'categories': '=DB_Tarefas!$A$2:$A$' + str(len(df_tarefas_status)+1),
            'values':     '=DB_Tarefas!$B$2:$B$' + str(len(df_tarefas_status)+1),
            'points': [{'fill': {'color': '#10B981'}}, {'fill': {'color': '#F59E0B'}}, {'fill': {'color': '#EF4444'}}],
        })
        c1.set_title({'name': 'Raio-X das Missões'})
        dashboard.insert_chart('B8', c1, {'x_scale': 1.1, 'y_scale': 1.1})

    # GRÁFICO 2: BAIRROS (BARRAS)
    if not df_bairros.empty:
        c2 = workbook.add_chart({'type': 'bar'})
        c2.add_series({
            'name': 'Apoiadores por Bairro',
            'categories': '=DB_Bairros!$A$2:$A$11', # Top 10
            'values':     '=DB_Bairros!$B$2:$B$11',
            'fill': {'color': '#4F46E5'}
        })
        c2.set_title({'name': 'Top 10 Bairros'})
        dashboard.insert_chart('F8', c2, {'x_scale': 1.1, 'y_scale': 1.1})

    # GRÁFICO 3: SEXO (COLUNAS)
    if not df_sexo.empty:
        c3 = workbook.add_chart({'type': 'column'})
        c3.add_series({
            'name': 'Distribuição por Sexo',
            'categories': '=DB_Sexo!$A$2:$A$5',
            'values':     '=DB_Sexo!$B$2:$B$5',
            'fill': {'color': '#EC4899'}
        })
        c3.set_title({'name': 'Perfil por Sexo'})
        dashboard.insert_chart('B25', c3, {'x_scale': 1.1, 'y_scale': 1.1})

    # GRÁFICO 4: IDADE (LINHA OU COLUNA)
    if not df_idade.empty:
        c4 = workbook.add_chart({'type': 'column'})
        c4.add_series({
            'name': 'Faixa Etária',
            'categories': '=DB_Idade!$A$2:$A$10',
            'values':     '=DB_Idade!$B$2:$B$10',
            'fill': {'color': '#3B82F6'}
        })
        c4.set_title({'name': 'Faixa Etária'})
        dashboard.insert_chart('F25', c4, {'x_scale': 1.1, 'y_scale': 1.1})

    writer.close()
    output.seek(0)

    # Geração do Nome do Arquivo
    data_hoje = datetime.now().strftime('%d-%m-%Y')
    random_id = random.randint(1000, 9999)
    filename = f"Relatorio de Campanha - {nome_candidato} - {data_hoje} - {random_id}.xlsx"
    
    return send_file(output, download_name=filename, as_attachment=True)