from flask import Blueprint, render_template, request, redirect, url_for, session
from ..utils.json_helper import load_data

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        usuarios = load_data('usuarios')
        user = next((u for u in usuarios if u['email'] == email and u['senha'] == senha), None)
        if user:
            session['user_id'] = user['id']
            session['cliente_id'] = user['cliente_id']
            return redirect(url_for('crm.dashboard_index'))
    return '''
        <h2>Login SaaS Político</h2>
        <form method="post">
            <input type="email" name="email" placeholder="admin@teste.com" required><br>
            <input type="password" name="senha" placeholder="123" required><br>
            <button type="submit">Entrar</button>
        </form>
    '''

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))