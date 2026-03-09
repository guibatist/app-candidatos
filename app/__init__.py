from flask import Flask
from app.routes.public import public_bp
from app.routes.auth import auth_bp
from app.routes.superadmin import superadmin_bp
from app.routes.crm import crm_bp

def create_app():
    app = Flask(__name__)
    app.secret_key = 'sua_chave_secreta'

    # 1. REGISTRE O SITE PRIMEIRO (Sem prefixo, ele é o dono da "/")
    app.register_blueprint(public_bp)

    # 2. AUTH (Geralmente /login, /logout)
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # 3. CRM (IMPORTANTE: Adicione um prefixo aqui para desocupar a "/")
    app.register_blueprint(crm_bp, url_prefix='/crm')

    # 4. SUPERADMIN
    app.register_blueprint(superadmin_bp, url_prefix='/master')

    return app