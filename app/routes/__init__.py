from flask import Flask
import os

def create_app():
    app = Flask(__name__)
    
    # Configurações Básicas
    app.config['SECRET_KEY'] = 'sua_chave_secreta_aqui_mude_em_producao'
    
    # Caminho para os dados JSON (se ainda for usar, embora estejamos indo pro Postgres)
    app.config['DATA_DIR'] = os.path.join(app.root_path, 'data')

    # Importação das Blueprints (Rotas)
    from app.routes.auth import auth_bp
    from app.routes.crm import crm_bp  # CORRIGIDO: de cm_bp para crm_bp
    from app.routes.superadmin import superadmin_bp # CORRIGIDO: Único admin
    
    # Registro das Blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(crm_bp, url_prefix='/crm') # CORRIGIDO: crm_bp
    
    # O painel master agora responde em /master
    # Ex: /master/clientes ou /master/dashboard
    app.register_blueprint(superadmin_bp, url_prefix='/master')
    
    # Rota de redirecionamento inicial
    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    return app