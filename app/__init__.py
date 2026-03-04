from flask import Flask, session, redirect, url_for
from .utils.json_helper import load_data

def create_app():
    app = Flask(__name__)
    app.secret_key = 'chave_secreta_teste'

    @app.context_processor
    def inject_permissions():
        user_id = session.get('user_id')
        if user_id:
            usuarios = load_data('usuarios')
            user = next((u for u in usuarios if u['id'] == user_id), None)
            if user:
                clientes = load_data('clientes')
                cliente = next((c for c in clientes if c['id'] == user['cliente_id']), None)
                planos = load_data('planos')
                plano = next((p for p in planos if p['id'] == cliente['plano_id']), None)
                return dict(permissoes=plano, usuario_logado=user)
        return dict(permissoes={}, usuario_logado=None)

    from .routes.auth import auth_bp
    from .routes.crm import crm_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(crm_bp, url_prefix='/crm')

    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app