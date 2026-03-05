from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from ..services.crm_service import CRMService
from app.services.crm_service import listar_tarefas_por_usuario, criar_tarefa
from app.utils.json_helper import filter_by_client
import json
import os
from datetime import datetime

crm_bp = Blueprint('crm', __name__)

# 1. DASHBOARD PRINCIPAL
@crm_bp.route('/')
def dashboard_index():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    role = session.get('role')

    # 1. Buscamos os dados do dashboard
    resumo = CRMService.get_dashboard_data(cliente_id)

    # 2. Criamos o objeto de permissões baseado no cargo/role
    # Aqui você define a lógica: candidatos e coordenadores veem tudo. 
    # Assessores talvez não vejam o mapa (exemplo).
    permissoes = {
        "permite_mapa": True, 
        "permite_equipe": True if role in ['candidato', 'coordenador'] else False,
        "permite_bi": True if role == 'candidato' else False
    }

    # 3. Enviamos 'permissoes' para o template
    return render_template('crm/dashboard.html', 
                           resumo=resumo, 
                           permissoes=permissoes)

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
@crm_bp.route('/apoiadores/<apoiador_id>', methods=['GET'])
def perfil_apoiador(apoiador_id):
    # 1. Garante que os dados da sessão não tenham espaços em branco
    cliente_id = str(session.get('cliente_id')).strip()
    usuario_id = str(session.get('user_id')).strip()
    role = str(session.get('role', '')).strip().lower() # Garante que fique 'admin' minúsculo

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path_tarefas = os.path.join(base_dir, 'data', 'tarefas.json')
    path_apoiadores = os.path.join(base_dir, 'data', 'apoiadores.json')
    path_usuarios = os.path.join(base_dir, 'data', 'usuarios.json')

    # 2. Carrega Apoiador
    apoiador = None
    if os.path.exists(path_apoiadores):
        with open(path_apoiadores, 'r', encoding='utf-8') as f:
            for a in json.load(f):
                if str(a.get('id')).strip() == str(apoiador_id).strip() and str(a.get('cliente_id')).strip() == cliente_id:
                    apoiador = a
                    break

    if not apoiador:
        flash('Apoiador não encontrado.', 'danger')
        return redirect(url_for('crm.listar_apoiadores'))

    # 3. MODO RAIO-X: Puxa TUDO sem filtro de equipe (Assessor/Admin) para testar
    tarefas_geral = []
    if os.path.exists(path_tarefas):
        with open(path_tarefas, 'r', encoding='utf-8') as f:
            for t in json.load(f):
                # Filtra apenas se a tarefa é deste apoiador e deste cliente
                if str(t.get('apoiador_id')).strip() == str(apoiador_id).strip() and str(t.get('cliente_id')).strip() == cliente_id:
                    tarefas_geral.append(t)

    # 4. Separa para garantir compatibilidade com qualquer HTML seu
    pendentes = [t for t in tarefas_geral if str(t.get('status', '')).lower() == 'pendente']
    historico = [t for t in tarefas_geral if str(t.get('status', '')).lower() in ['concluida', 'cancelada']]

    assessores = []
    if os.path.exists(path_usuarios):
        with open(path_usuarios, 'r', encoding='utf-8') as f:
            assessores = [u for u in json.load(f) if str(u.get('cliente_id')).strip() == cliente_id and str(u.get('role')).lower() == 'assessor']

    return render_template(
        'crm/perfil_apoiador.html', 
        apoiador=apoiador,
        tarefas=tarefas_geral,  # Se seu HTML usa {% for t in tarefas %}
        pendentes=pendentes,    # Se seu HTML usa {% for t in pendentes %}
        historico=historico,    # Se seu HTML usa {% for t in historico %}
        todas_tarefas=tarefas_geral,
        assessores=assessores,
        user_role=role
    )

# 5. EXCLUIR APOIADOR
@crm_bp.route('/apoiadores/excluir/<int:id>', methods=['POST'])
def excluir_apoiador(id):
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    cliente_id = session.get('cliente_id')
    CRMService.excluir_apoiador(cliente_id, id)
    return redirect(url_for('crm.listar_apoiadores'))

# 6. CRIAR NOVA TAREFA PARA O APOIADOR
@crm_bp.route('/apoiadores/<apoiador_id>/tarefas', methods=['POST'])
def nova_tarefa(apoiador_id):
    cliente_id = session.get('cliente_id')
    
    # Coleta dados do form
    tipo = request.form.get('tipo')
    data_limite = request.form.get('data_limite')
    descricao = request.form.get('descricao')
    assessor_id = request.form.get('assessor_id')

    # CAMINHO CORRETO: Garante que salve em app/data/tarefas.json
    diretorio_atual = os.path.dirname(os.path.abspath(__file__)) # app/routes
    pasta_data = os.path.join(os.path.dirname(diretorio_atual), 'data') # app/data
    caminho_tarefas = os.path.join(pasta_data, 'tarefas.json')

    try:
        tarefas = []
        if os.path.exists(caminho_tarefas):
            with open(caminho_tarefas, 'r', encoding='utf-8') as f:
                tarefas = json.load(f)

        # Criar nova tarefa com ID único e status minúsculo
        nova_acao = {
            "id": str(len(tarefas) + 1 + int(os.times().elapsed)), # ID mais dinâmico
            "cliente_id": str(cliente_id),
            "apoiador_id": str(apoiador_id),
            "tipo": tipo,
            "data_limite": data_limite,
            "descricao": descricao,
            "assessor_id": assessor_id if assessor_id else None,
            "status": "pendente", # IMPORTANTE: Minúsculo para bater com o HTML
            "data_criacao": datetime.now().strftime("%d/%m/%Y %H:%M")
        }

        tarefas.append(nova_acao)
        
        with open(caminho_tarefas, 'w', encoding='utf-8') as f:
            json.dump(tarefas, f, indent=4, ensure_ascii=False)
            
        flash('Ação agendada!', 'success')
    except Exception as e:
        print(f"Erro ao salvar: {e}")
        flash('Erro ao salvar tarefa.', 'danger')

    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

# 7. ALTERAÇÃO DA FASE DA TAREFA - PENDENTE, CONCLUÍDA OU CANCELADA
@crm_bp.route('/tarefas/<id>/status', methods=['POST'])
def atualizar_status_tarefa(id):
    cliente_id = str(session.get('cliente_id'))
    apoiador_id = request.form.get('apoiador_id')
    novo_status = request.form.get('status') # Recebe: pendente, concluida ou cancelada
    
    diretorio_atual = os.path.abspath(os.path.dirname(__file__))
    caminho_tarefas = os.path.join(os.path.dirname(diretorio_atual), 'data', 'tarefas.json')

    try:
        with open(caminho_tarefas, 'r', encoding='utf-8') as f:
            tarefas = json.load(f)
        
        # Procura a tarefa e atualiza
        for t in tarefas:
            if str(t.get('id')) == str(id) and str(t.get('cliente_id')) == cliente_id:
                t['status'] = novo_status.lower()
                break
        
        with open(caminho_tarefas, 'w', encoding='utf-8') as f:
            json.dump(tarefas, f, indent=4, ensure_ascii=False)
            
        flash(f'Status da tarefa atualizado com sucesso!', 'success')
    except Exception as e:
        print(f"Erro ao atualizar status: {e}")
        flash('Erro ao atualizar a tarefa.', 'danger')

    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

# 8. EDIÇÃO DE HISTÓRICO E TAREFAS PENDENTES
@crm_bp.route('/tarefas/<id>/editar', methods=['POST'])
def editar_tarefa(id):
    cliente_id = str(session.get('cliente_id'))
    apoiador_id = request.form.get('apoiador_id')
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path_tarefas = os.path.join(base_dir, 'data', 'tarefas.json')

    try:
        with open(path_tarefas, 'r', encoding='utf-8') as f:
            tarefas = json.load(f)
        
        for t in tarefas:
            if str(t.get('id')) == str(id) and str(t.get('cliente_id')) == cliente_id:
                t['tipo'] = request.form.get('tipo')
                t['data_limite'] = request.form.get('data_limite')
                t['descricao'] = request.form.get('descricao')
                t['assessor_id'] = request.form.get('assessor_id')
                break
        
        with open(path_tarefas, 'w', encoding='utf-8') as f:
            json.dump(tarefas, f, indent=4, ensure_ascii=False)
        flash('Tarefa atualizada!', 'success')
    except Exception as e:
        flash('Erro ao editar tarefa.', 'danger')

    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))


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
 