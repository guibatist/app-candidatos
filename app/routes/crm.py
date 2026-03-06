from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from ..services.crm_service import CRMService
from app.services.crm_service import listar_tarefas_por_usuario, criar_tarefa
from app.utils.json_helper import filter_by_client, load_data
import json
import os
from datetime import datetime
import random

crm_bp = Blueprint('crm', __name__)

# --- FUNÇÃO AUXILIAR DE CONTEXTO (MANTIDA NO TOPO PARA USO GLOBAL) ---
def obter_contexto_acesso():
    if 'user_id' not in session:
        return None
    
    role = session.get('role')
    # Regras de negócio centralizadas para a Sidebar
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

# 1. DASHBOARD PRINCIPAL
@crm_bp.route('/')
def dashboard_index():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    resumo = CRMService.get_dashboard_data(ctx['cliente_id'])

    return render_template('crm/dashboard.html', 
                           resumo=resumo, 
                           permissoes=ctx['permissoes'])

# 2. LISTAR APOIADORES
@crm_bp.route('/apoiadores')
def listar_apoiadores():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))

    apoiadores = CRMService.get_apoiadores(ctx['cliente_id'])

    return render_template('crm/apoiadores.html', 
                           apoiadores=apoiadores, 
                           permissoes=ctx['permissoes'])

# 3. CADASTRAR NOVO APOIADOR
@crm_bp.route('/apoiadores/novo', methods=['GET', 'POST'])
def novo_apoiador():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        CRMService.adicionar_apoiador(ctx['cliente_id'], request.form)
        return redirect(url_for('crm.listar_apoiadores'))
        
    return render_template('crm/form_apoiador.html', 
                           permissoes=ctx['permissoes']) # Corrigido aqui

# 4. PERFIL DO APOIADOR
@crm_bp.route('/apoiadores/<apoiador_id>', methods=['GET'])
def perfil_apoiador(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))

    cliente_id = str(ctx['cliente_id']).strip()
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path_tarefas = os.path.join(base_dir, 'data', 'tarefas.json')
    path_apoiadores = os.path.join(base_dir, 'data', 'apoiadores.json')
    path_usuarios = os.path.join(base_dir, 'data', 'usuarios.json')

    # Carrega Apoiador
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

    tarefas_geral = []
    if os.path.exists(path_tarefas):
        with open(path_tarefas, 'r', encoding='utf-8') as f:
            for t in json.load(f):
                if str(t.get('apoiador_id')).strip() == str(apoiador_id).strip() and str(t.get('cliente_id')).strip() == cliente_id:
                    tarefas_geral.append(t)

    pendentes = [t for t in tarefas_geral if str(t.get('status', '')).lower() == 'pendente']
    historico = [t for t in tarefas_geral if str(t.get('status', '')).lower() in ['concluida', 'cancelada']]

    assessores = []
    if os.path.exists(path_usuarios):
        with open(path_usuarios, 'r', encoding='utf-8') as f:
            assessores = [u for u in json.load(f) if str(u.get('cliente_id')).strip() == cliente_id and str(u.get('role')).lower() == 'assessor']

    return render_template(
        'crm/perfil_apoiador.html', 
        apoiador=apoiador,
        tarefas=tarefas_geral,
        pendentes=pendentes,
        historico=historico,
        todas_tarefas=tarefas_geral,
        assessores=assessores,
        user_role=ctx['role'],
        permissoes=ctx['permissoes'] # Corrigido aqui
    )

# 5. MAPA DE BAIRROS
@crm_bp.route('/mapa')
def mapa_bairros():
    ctx = obter_contexto_acesso()
    if not ctx: 
        return redirect(url_for('auth.login'))
    
    from app.utils.json_helper import load_data
    clientes = load_data('clientes')
    planos = load_data('planos')
    
    # --- LOGS DE DEBUG (Olhe o terminal quando clicar no mapa) ---
    cid_sessao = ctx['cliente_id']
    print(f"DEBUG: ID na Sessão: '{cid_sessao}' (Tipo: {type(cid_sessao)})")
    print(f"DEBUG: Clientes no JSON: {[{'id': c['id'], 'tipo': type(c['id'])} for c in clientes]}")
    # -------------------------------------------------------------

    # Busca o cliente forçando ambos os lados para STRING
    cliente = next((c for c in clientes if str(c.get('id')) == str(cid_sessao)), None)
    
    if not cliente:
        print("ERRO: Cliente não localizado após comparação!")
        flash('Campanha não localizada no banco de dados.', 'danger')
        return redirect(url_for('crm.dashboard_index'))
        
    # Busca o plano forçando string no ID do plano também
    plano = next((p for p in planos if str(p.get('id')) == str(cliente.get('plano_id'))), None)
    
    if not plano:
        print(f"ERRO: Plano ID {cliente.get('plano_id')} não encontrado no planos.json")
        flash('Plano de acesso não configurado.', 'warning')
        return redirect(url_for('crm.dashboard_index'))

    if not plano.get('permite_mapa'):
        return render_template('crm/erro_plano.html', modulo="Mapa", permissoes=ctx['permissoes']), 403

    dados_mapa = CRMService.get_dados_mapa(ctx['cliente_id'])
    
    return render_template('crm/mapa.html', 
                           dados_mapa=dados_mapa, 
                           permissoes=ctx['permissoes'])
# 6. LISTAR EQUIPE
@crm_bp.route('/equipe')
def listar_equipe():
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    
    equipe_total = CRMService.get_equipe_completa(ctx['cliente_id'])
    
    candidato_lider = next((m for m in equipe_total if m.get('role') == 'candidato'), None)
    eu = next((m for m in equipe_total if str(m.get('id')) == str(session.get('user_id'))), None)
    
    outros = [m for m in equipe_total if m != candidato_lider and m != eu]
    random.shuffle(outros)

    lista_final = []
    if ctx['role'] == 'candidato':
        if eu: lista_final.append(eu)
        lista_final.extend(outros)
    else:
        if candidato_lider: lista_final.append(candidato_lider)
        if eu: lista_final.append(eu)
        lista_final.extend(outros)

    return render_template('crm/equipe.html', 
                           equipe=lista_final, 
                           permissoes=ctx['permissoes'],
                           meu_id=str(session.get('user_id')))

# --- ROTAS DE AÇÃO (REDIRECTS NÃO PRECISAM DE PERMISSOES NO RENDER) ---

@crm_bp.route('/apoiadores/excluir/<int:id>', methods=['POST'])
def excluir_apoiador(id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))
    CRMService.excluir_apoiador(ctx['cliente_id'], id)
    return redirect(url_for('crm.listar_apoiadores'))

@crm_bp.route('/apoiadores/<apoiador_id>/tarefas', methods=['POST'])
def nova_tarefa(apoiador_id):
    ctx = obter_contexto_acesso()
    # ... (lógica de salvar tarefa mantida igual)
    # Garanta que o redirect no final use o ctx['cliente_id']
    return redirect(url_for('crm.perfil_apoiador', apoiador_id=apoiador_id))

@crm_bp.route('/api/apoiadores/busca')
def api_busca_apoiadores():
    ctx = obter_contexto_acesso()
    if not ctx: return jsonify([])
    termo = request.args.get('q', '')
    resultados = CRMService.buscar_apoiadores_por_nome(ctx['cliente_id'], termo)
    return jsonify(resultados)