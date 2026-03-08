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

# 5. PERFIL DO APOIADOR (MIGRAÇÃO PARCIAL PARA SERVICE)
@crm_bp.route('/apoiadores/<apoiador_id>')
def perfil_apoiador(apoiador_id):
    ctx = obter_contexto_acesso()
    if not ctx: return redirect(url_for('auth.login'))

    # Usaremos o service para buscar os dados no banco
    # Se você ainda não migrou o get_apoiador_by_id no service,
    # ele pode dar erro. Mas para o mapa funcionar, a rota acima já basta.
    apoiadores = CRMService.get_apoiadores(ctx['cliente_id'])
    apoiador = next((a for a in apoiadores if str(a['id']) == str(apoiador_id)), None)

    if not apoiador:
        flash('Apoiador não encontrado.', 'danger')
        return redirect(url_for('crm.listar_apoiadores'))

    return render_template('crm/perfil_apoiador.html', 
                           apoiador=apoiador, 
                           permissoes=ctx['permissoes'])

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