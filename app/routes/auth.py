import os
import json
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

# Configuração de Caminho Absoluto
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH_USUARIOS = os.path.join(base_dir, 'data', 'usuarios.json')

def load_usuarios():
    if os.path.exists(PATH_USUARIOS):
        with open(PATH_USUARIOS, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
    return []

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Objeto para evitar o erro 'permissoes is undefined' no base.html
    permissoes_vazias = {
        "permite_mapa": False,
        "permite_equipe": False,
        "permite_bi": False
    }

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        usuarios = load_usuarios()
        
        # Busca o usuário pelo e-mail
        usuario = next((u for u in usuarios if u.get('email', '').lower() == email), None)

        if usuario and check_password_hash(usuario['senha'], password):
            session.clear()

            # Dados de Sessão
            session['user_id'] = usuario.get('id')
            session['cliente_id'] = usuario.get('cliente_id')
            session['role'] = usuario.get('role')
            session['nome'] = usuario.get('nome')

            # Redirecionamento por cargo
            if usuario.get('role') == 'superadmin':
                return redirect(url_for('superadmin.painel_geral'))
            
            return redirect(url_for('crm.dashboard_index'))
        
        flash('E-mail ou senha incorretos.', 'danger')
        return render_template('auth/login.html', permissoes=permissoes_vazias)
        
    # GET: Carrega a página enviando as permissões falsas para não quebrar o base.html
    return render_template('auth/login.html', permissoes=permissoes_vazias)

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('auth.login'))