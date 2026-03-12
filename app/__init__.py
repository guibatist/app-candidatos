from flask import Flask, session
from app.routes.public import public_bp
from app.routes.auth import auth_bp
from app.routes.superadmin import superadmin_bp
from app.routes.crm import crm_bp
from app.utils.db import get_db_connection
from flask_mail import Mail, Message # Import Message aqui
from dotenv import load_dotenv
import os
import uuid # Necessário para o Ticket ID

# 1. Carrega o .env antes de tudo
load_dotenv()

# 2. Instancia o Mail aqui fora (Global)
mail = Mail()

def enviar_alerta_sistema(destinatario, nome_usuario, tipo_alerta, descricao):
    """
    Função robusta para enviar e-mails sem agrupamento (threading) no Gmail.
    """
    from flask import current_app
    
    # Geramos um ID único para o assunto para o Gmail não empilhar os e-mails
    ticket_id = uuid.uuid4().hex[:6].upper()
    assunto = f"[{ticket_id}] {tipo_alerta}"
    
    msg = Message(assunto, recipients=[destinatario])
    
    # Template HTML profissional
    msg.html = f"""
    <div style="font-family: sans-serif; color: #334155; max-width: 600px; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden;">
        <div style="background: #4f46e5; padding: 20px; text-align: center;">
            <h2 style="color: #ffffff; margin: 0;">VotaHub CRM</h2>
        </div>
        <div style="padding: 25px;">
            <p>Olá, <strong>{nome_usuario}</strong>,</p>
            <p>Você tem uma nova atualização no sistema:</p>
            <div style="background: #f8fafc; border-left: 4px solid #4f46e5; padding: 15px; margin: 20px 0;">
                <strong style="color: #4f46e5;">{tipo_alerta}</strong><br>
                <span style="font-size: 14px; color: #64748b;">{descricao}</span>
            </div>
            <p style="font-size: 11px; color: #94a3b8; text-align: center;">Ref Ticket: {ticket_id}</p>
        </div>
    </div>
    """
    
    try:
        with current_app.app_context():
            mail.send(msg)
            print(f"[MAIL-OK] Enviado para {destinatario} com Ticket {ticket_id}")
    except Exception as e:
        print(f"[MAIL-ERROR] Falha ao disparar e-mail: {e}")

def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv('SECRET_KEY', 'sua_chave_secreta_padrao')
    
    # --- CONFIGURAÇÃO SMTP (USANDO SEUS NOMES DO .ENV) ---
    app.config['MAIL_SERVER'] = os.getenv('SMTP_HOST')
    app.config['MAIL_PORT'] = int(os.getenv('SMTP_PORT', 587))
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USE_SSL'] = False
    app.config['MAIL_USERNAME'] = os.getenv('SMTP_USER')
    app.config['MAIL_PASSWORD'] = os.getenv('SMTP_PASS')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('SMTP_USER')

    # Inicializa o mail com o app
    mail.init_app(app)

    # --- INJEÇÃO GLOBAL DE NOTIFICAÇÕES (SIDEBAR) ---
    @app.context_processor
    def inject_notificacoes():
        user_id = session.get('user_id')
        if not user_id:
            return dict(total_notificacoes=0)
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # CONTA TAREFAS NÃO LIDAS
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

    # Registro de Blueprints
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(crm_bp, url_prefix='/crm')
    app.register_blueprint(superadmin_bp, url_prefix='/master')

    return app