from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from ..services.crm_service import CRMService
import os
import json

crm_bp = Blueprint('crm', __name__)

def obter_contexto_acesso():
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

# 1. DASHBOARD
@crm_bp.route('/')
def dashboard_index():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    resumo = CRMService.get_dashboard_data(ctx['cliente_id'])
    return render_template('crm/dashboard.html', resumo=resumo, permissoes=ctx['permissoes'])

# 2. LISTAR APOIADORES
@crm_bp.route('/apoiadores')
def listar_apoiadores():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    apoiadores = CRMService.get_apoiadores(ctx['cliente_id'])
    return render_template('crm/apoiadores.html', apoiadores=apoiadores, permissoes=ctx['permissoes'])

# 3. NOVO APOIADOR
@crm_bp.route('/apoiadores/novo', methods=['GET', 'POST'])
def novo_apoiador():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    if request.method == 'POST':
        CRMService.adicionar_apoiador(ctx['cliente_id'], request.form)
        return redirect(url_for('crm.listar_apoiadores'))
    return render_template('crm/form_apoiador.html', permissoes=ctx['permissoes'])

# 4. MAPA (GEOINTELIGÊNCIA) - REFATORADO PARA SQL
@crm_bp.route('/mapa')
def mapa_bairros():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    # Removida a dependência de planos.json e clientes.json
    # Se o usuário tem a permissão no ctx, ele acessa os dados do Postgres
    if not ctx['permissoes']['permite_mapa']:
        flash('Seu perfil não tem acesso ao mapa.', 'warning')
        return redirect(url_for('crm.dashboard_index'))

    dados_mapa = CRMService.get_dados_mapa(ctx['cliente_id'])
    
    return render_template('crm/mapa.html', 
                           dados_mapa=dados_mapa, 
                           permissoes=ctx['permissoes'])

from app.utils.db import get_db_connection
from psycopg2.extras import RealDictCursor

# 5. PERFIL DO APOIADOR (100% POSTGRESQL)
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

# --- ROTAS DE AÇÃO (TAREFAS E EXCLUSÃO) ---

@crm_bp.route('/apoiadores/<apoiador_id>/tarefas', methods=['POST'])
def nova_tarefa(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    CRMService.adicionar_tarefa(ctx['cliente_id'], apoiador_id, request.form)
    flash('Tarefa adicionada com sucesso!', 'success')
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

@crm_bp.route('/apoiadores/excluir/<apoiador_id>', methods=['POST'])
def excluir_apoiador(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    CRMService.excluir_apoiador(ctx['cliente_id'], apoiador_id)
    flash('Apoiador excluído permanentemente.', 'warning')
    return redirect(url_for('crm.listar_apoiadores'))

# 6. EQUIPE
@crm_bp.route('/equipe')
def listar_equipe():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    equipe = CRMService.get_equipe_completa(ctx['cliente_id'])
    return render_template('crm/equipe.html', equipe=equipe, permissoes=ctx['permissoes'])

@crm_bp.route('/api/apoiadores/busca')
def api_busca_apoiadores():
    ctx = obter_contexto_acesso()
    if not ctx: return jsonify([])
    termo = request.args.get('q', '')
    resultados = CRMService.buscar_apoiadores_por_nome(ctx['cliente_id'], termo)
    return jsonify(resultados)

@crm_bp.route('/tarefas/<id>/atualizar', methods=['POST'])
def atualizar_status_tarefa(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    # Agora o Flask vai ler o que escolheu no dropdown!
    novo_status = request.form.get('status', 'concluida')
    
    # Chama o novo serviço que sabe lidar com estados dinâmicos
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

@crm_bp.route('/apoiadores/<id>/editar-perfil', methods=['POST'])
def editar_perfil_detalhado(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    # Chama o service para atualizar os dados demográficos no banco
    CRMService.atualizar_perfil_demografico(ctx['cliente_id'], id, request.form)
    
    flash('Perfil demográfico atualizado com sucesso!', 'success')
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=id))