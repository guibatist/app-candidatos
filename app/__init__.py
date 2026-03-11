from flask import Flask, session # Adicionado session
from app.routes.public import public_bp
from app.routes.auth import auth_bp
from app.routes.superadmin import superadmin_bp
from app.routes.crm import crm_bp
from app.utils.db import get_db_connection # Importe sua conexão aqui

def create_app():
    app = Flask(__name__)
    app.secret_key = 'sua_chave_secreta'

    # --- INJEÇÃO GLOBAL DE NOTIFICAÇÕES ---
    @app.context_processor
    def inject_notificacoes():
        user_id = session.get('user_id')
        if not user_id:
            return dict(total_notificacoes=0)
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # CONTA TAREFAS NÃO LIDAS (AQUI É O SEGREDO)
                cursor.execute("""
                    SELECT COUNT(id) FROM tarefas 
                    WHERE (assessor_id = %s OR cliente_id = %s) 
                    AND lida = FALSE
                """, (user_id, user_id))
                t = cursor.fetchone()[0] or 0
                
                # CONTA MENSAGENS NÃO LIDAS
                cursor.execute("""
                    SELECT COUNT(id) FROM mensagens 
                    WHERE destinatario_id = %s AND lida = FALSE AND apagada = FALSE
                """, (user_id,))
                m = cursor.fetchone()[0] or 0
                
                return dict(total_notificacoes = t + m)
        except:
            return dict(total_notificacoes=0)
        finally:
            if conn: conn.close()
    # ---------------------------------------

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(crm_bp, url_prefix='/crm')
    app.register_blueprint(superadmin_bp, url_prefix='/master')

    return app