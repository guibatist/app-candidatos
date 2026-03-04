from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from ..services.crm_service import CRMService

crm_bp = Blueprint('crm', __name__)

# 1. DASHBOARD PRINCIPAL
@crm_bp.route('/')
def dashboard_index():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    resumo = CRMService.get_dashboard_data(cliente_id)
    return render_template('crm/dashboard.html', resumo=resumo)

# 2. LISTAR TODOS OS APOIADORES (Aqui estava o seu erro 404)
@crm_bp.route('/apoiadores')
def listar_apoiadores():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    apoiadores = CRMService.listar_apoiadores(cliente_id)
    return render_template('crm/apoiadores.html', apoiadores=apoiadores)

# 3. CADASTRAR NOVO APOIADOR
@crm_bp.route('/apoiadores/novo', methods=['GET', 'POST'])
def novo_apoiador():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    
    if request.method == 'POST':
        CRMService.adicionar_apoiador(cliente_id, request.form)
        return redirect(url_for('crm.listar_apoiadores'))
        
    return render_template('crm/form_apoiador.html')

# 4. PERFIL DO APOIADOR (Onde ficam as Tarefas)
@crm_bp.route('/apoiadores/<int:id>')
def perfil_apoiador(id):
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    
    apoiador = CRMService.get_apoiador(cliente_id, id)
    if not apoiador: 
        return "Apoiador não encontrado", 404
    
    tarefas = CRMService.listar_tarefas_apoiador(cliente_id, id)
    return render_template('crm/perfil_apoiador.html', apoiador=apoiador, tarefas=tarefas)

# 5. EXCLUIR APOIADOR
@crm_bp.route('/apoiadores/excluir/<int:id>', methods=['POST'])
def excluir_apoiador(id):
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    CRMService.excluir_apoiador(cliente_id, id)
    return redirect(url_for('crm.listar_apoiadores'))

# 6. CRIAR NOVA TAREFA PARA O APOIADOR
@crm_bp.route('/apoiadores/<int:id>/tarefas', methods=['POST'])
def nova_tarefa(id):
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    CRMService.adicionar_tarefa(cliente_id, id, request.form)
    
    # Redireciona de volta para o perfil do apoiador
    return redirect(url_for('crm.perfil_apoiador', id=id))

# 7. MARCAR TAREFA COMO CONCLUÍDA
@crm_bp.route('/tarefas/<int:id>/concluir', methods=['POST'])
def concluir_tarefa(id):
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    CRMService.concluir_tarefa(cliente_id, id)
    
    # Redireciona para a mesma página que o usuário estava (refresh)
    return redirect(request.referrer)

from ..utils.json_helper import load_data

@crm_bp.route('/mapa')
def mapa_bairros():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    # Verificação de Permissão do Plano
    cliente_id = session.get('cliente_id')
    clientes = load_data('clientes')
    planos = load_data('planos')
    
    cliente = next((c for c in clientes if c['id'] == cliente_id), None)
    plano = next((p for p in planos if p['id'] == cliente['plano_id']), None)
    
    if not plano or not plano.get('permite_mapa'):
        return render_template('crm/erro_plano.html', modulo="Mapa Interativo"), 403

    # Busca os dados agrupados
    dados_mapa = CRMService.get_dados_mapa(cliente_id)
    
    return render_template('crm/mapa.html', dados_mapa=dados_mapa)

# (Adicione isso no final do crm.py)
@crm_bp.route('/api/apoiadores/busca')
def api_busca_apoiadores():
    if 'user_id' not in session: 
        return jsonify([])
        
    cliente_id = session.get('cliente_id')
    termo = request.args.get('q', '')
    
    if not termo: 
        return jsonify([])
        
    resultados = CRMService.buscar_apoiadores_por_nome(cliente_id, termo)
    return jsonify(resultados)

# ================= ROTAS DE EQUIPE =================

@crm_bp.route('/equipe')
def listar_equipe():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    # Traz a equipe já com o cálculo de metas batidas
    dados_equipe = CRMService.get_progresso_equipe(cliente_id)
    
    return render_template('crm/equipe.html', equipe=dados_equipe)

@crm_bp.route('/equipe/novo', methods=['POST'])
def nova_equipe():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    CRMService.adicionar_membro_equipe(cliente_id, request.form)
    
    return redirect(url_for('crm.listar_equipe'))

@crm_bp.route('/equipe/excluir/<int:id>', methods=['POST'])
def excluir_equipe(id):
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    CRMService.excluir_membro_equipe(cliente_id, id)
    
    return redirect(url_for('crm.listar_equipe'))
    return redirect(url_for('crm.listar_equipe'))