import os
import json
import time
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash

# Blueprint limpa (o prefixo '/master' agora é injetado pelo __init__.py)
superadmin_bp = Blueprint('superadmin', __name__)

# Configuração de Caminhos Absolutos
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH_CAMPANHAS = os.path.join(base_dir, 'data', 'campanhas.json')
PATH_USUARIOS = os.path.join(base_dir, 'data', 'usuarios.json')

# Funções Auxiliares
def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def is_superadmin():
    # Comente a linha real e retorne True temporariamente
    # return session.get('role') == 'superadmin'
    return True

# ==========================================
# ROTAS DO PAINEL MASTER
# ==========================================

@superadmin_bp.route('/dashboard')
def painel_geral():
    if not is_superadmin():
        flash('Acesso negado.', 'danger')
        return redirect(url_for('auth.login'))
    
    campanhas = load_json(PATH_CAMPANHAS)
    usuarios = load_json(PATH_USUARIOS)
    
    for camp in campanhas:
        camp['usuarios'] = [u for u in usuarios if str(u.get('cliente_id')) == str(camp.get('id'))]

    # CRIAMOS O OBJETO QUE O SEU BASE.HTML ESTÁ PEDINDO
    # Ajuste os nomes dos campos de acordo com o que o seu base.html pede
    permissoes_mock = {
        "permite_mapa": True,
        "permite_equipe": True,
        "permite_bi": True
    }
        
    # ENVIAMOS 'permissoes' PARA O TEMPLATE
    return render_template('superadmin/dashboard.html', 
                           campanhas=campanhas, 
                           permissoes=permissoes_mock)

@superadmin_bp.route('/campanhas/nova', methods=['POST'])
def criar_campanha():
    if not is_superadmin():
        return redirect(url_for('auth.login'))
    
    nome_campanha = request.form.get('nome_campanha')
    nome_candidato = request.form.get('nome_candidato')
    email_candidato = request.form.get('email_candidato')
    
    campanhas = load_json(PATH_CAMPANHAS)
    usuarios = load_json(PATH_USUARIOS)
    
    campanha_id = f"camp_{int(time.time())}"
    
    nova_campanha = {
        "id": campanha_id,
        "nome_campanha": nome_campanha,
        "candidato_nome": nome_candidato,
        "status": "ativo",
        "data_criacao": time.strftime("%d/%m/%Y")
    }
    campanhas.append(nova_campanha)
    save_json(PATH_CAMPANHAS, campanhas)
    
    novo_usuario_candidato = {
        "id": f"usr_{int(time.time())}",
        "cliente_id": campanha_id,
        "nome": nome_candidato,
        "email": email_candidato,
        "role": "candidato",
        "senha": generate_password_hash("Mudar@123"),
        "precisa_trocar_senha": True
    }
    usuarios.append(novo_usuario_candidato)
    save_json(PATH_USUARIOS, usuarios)
    
    flash('Campanha criada! Senha inicial: Mudar@123', 'success')
    return redirect(url_for('superadmin.painel_geral'))

@superadmin_bp.route('/campanhas/<campanha_id>/assessores', methods=['POST'])
def adicionar_assessor(campanha_id):
    if not is_superadmin():
        return redirect(url_for('auth.login'))
    
    nome = request.form.get('nome')
    email = request.form.get('email')
    cargo = request.form.get('cargo', 'Assessor')
    meta_apoiadores = request.form.get('meta_apoiadores', 50)
    
    usuarios = load_json(PATH_USUARIOS)
    
    novo_assessor = {
        "id": f"usr_{int(time.time())}",
        "cliente_id": str(campanha_id),
        "nome": nome,
        "email": email,
        "role": "assessor",
        "cargo": cargo,
        "meta_apoiadores": int(meta_apoiadores),
        "senha": generate_password_hash("Acesso@123"),
        "precisa_trocar_senha": True
    }
    usuarios.append(novo_assessor)
    save_json(PATH_USUARIOS, usuarios)
    
    flash(f'Acesso criado para {nome}. Senha inicial: Acesso@123', 'success')
    return redirect(url_for('superadmin.painel_geral'))

@superadmin_bp.route('/usuarios/<usuario_id>/excluir', methods=['POST'])
def excluir_usuario(usuario_id):
    if not is_superadmin():
        return redirect(url_for('auth.login'))
        
    usuarios = load_json(PATH_USUARIOS)
    usuarios_restantes = [u for u in usuarios if str(u.get('id')) != str(usuario_id)]
    
    save_json(PATH_USUARIOS, usuarios_restantes)
    flash('Acesso revogado com sucesso.', 'warning')
    
    return redirect(url_for('superadmin.painel_geral'))