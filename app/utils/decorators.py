from flask import session, redirect, url_for, abort
from functools import wraps
from .json_helper import load_data

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def exige_permissao(permissao):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            usuarios = load_data('usuarios')
            user = next((u for u in usuarios if u['id'] == session.get('user_id')), None)
            
            clientes = load_data('clientes')
            cliente = next((c for c in clientes if c['id'] == user['cliente_id']), None)
            
            planos = load_data('planos')
            plano = next((p for p in planos if p['id'] == cliente['plano_id']), None)
            
            if not plano.get(permissao, False):
                abort(403) # Proibido
            return f(*args, **kwargs)
        return decorated_function
    return decorator