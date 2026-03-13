from flask import render_template
import secrets
import string
from app.utils.db import get_db_connection

class Mailer:
    @staticmethod
    def _registrar_log(email, protocolo, tipo, usuario_id=None, cliente_id=None):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO logs_emails (email_destinatario, protocolo, tipo_alerta, usuario_id, cliente_id)
                    VALUES (%s, %s, %s, %s, %s)
                """, (email, protocolo, tipo, usuario_id, cliente_id))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def gerar_protocolo():
        """Gera um ID curto aleatório para evitar agrupamento de e-mails (ex: #VP928)."""
        chars = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(chars) for _ in range(5))

    @staticmethod
    def enviar_primeiro_acesso(email, nome, senha="mudar@votahub"):
        from app.routes.auth import disparar_email_assincrono 
        protocolo = Mailer.gerar_protocolo()
        
        html = render_template('emails/primeiro_acesso.html', nome=nome, email=email, senha=senha, protocolo=protocolo)
        # Assunto dinâmico com Protocolo
        assunto = f"Bem-vindo ao VotoImpacto [Ref: #{protocolo}]"
        disparar_email_assincrono(email, assunto, html)

    @staticmethod
    def enviar_reset_senha(email, nome, senha="mudar@votahub"):
        from app.routes.auth import disparar_email_assincrono 
        protocolo = Mailer.gerar_protocolo()
        
        html = render_template('emails/reset_senha.html', nome=nome, email=email, senha=senha, protocolo=protocolo)
        assunto = f"Acesso Redefinido [Ref: #{protocolo}]"
        disparar_email_assincrono(email, assunto, html)

    @staticmethod
    def enviar_codigo_2fa(email, nome, codigo):
        from app.routes.auth import disparar_email_assincrono 
        protocolo = Mailer.gerar_protocolo()
        
        html = render_template('emails/codigo_2fa.html', nome=nome, codigo=codigo, protocolo=protocolo)
        assunto = f"Seu Código de Acesso [Ref: #{protocolo}]"
        disparar_email_assincrono(email, assunto, html)

    @staticmethod
    def enviar_boas_vindas_manual(email, nome):
        from app.routes.auth import disparar_email_assincrono 
        protocolo = Mailer.gerar_protocolo()
        
        html = render_template('emails/boas_vindas_manual.html', nome=nome, protocolo=protocolo)
        assunto = f"Conta Ativada - Manual do Usuário [Ref: #{protocolo}]"
        disparar_email_assincrono(email, assunto, html)

    @staticmethod
    def enviar_aviso_sistema(email, nome_usuario, tipo_alerta, descricao):
        from app.routes.auth import disparar_email_assincrono
        from flask import render_template
        
        protocolo = Mailer.gerar_protocolo()
        assunto = f"{tipo_alerta} [Ref: #{protocolo}]"
        
        # O render_template pega o HTML e substitui as variáveis
        html = render_template(
            'emails/aviso_sistema.html',
            nome_usuario=nome_usuario,
            tipo_alerta=tipo_alerta,
            descricao=descricao, # A string "Você foi designado..." entra aqui
            protocolo=protocolo
        )
        
        disparar_email_assincrono(email, assunto, html)

    @staticmethod
    def enviar_re_onboarding(email, nome, senha="mudar@votahub"):
        """E-mail para quando o admin altera o e-mail ou reseta a conta por erro."""
        from app.routes.auth import disparar_email_assincrono 
        protocolo = Mailer.gerar_protocolo()
        
        html = render_template('emails/re_onboarding.html', nome=nome, email=email, senha=senha, protocolo=protocolo)
        assunto = f"Atualização de Credenciais [Ref: #{protocolo}]"
        disparar_email_assincrono(email, assunto, html)