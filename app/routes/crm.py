from flask import Blueprint, render_template, session, redirect, url_for, request
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