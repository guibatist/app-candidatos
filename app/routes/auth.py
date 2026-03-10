import os
import re
import random
import string
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from psycopg2.extras import RealDictCursor
from app.utils.db import get_db_connection
# Autenticação .env para o gmail
from dotenv import load_dotenv


load_dotenv()

auth_bp = Blueprint('auth', __name__)

# ==========================================
# UTILITÁRIOS DE SEGURANÇA E NOTIFICAÇÃO
# ==========================================

def gerar_codigo_verificacao_numerico(tamanho=6):
    """Gera um código 2FA estritamente numérico para melhor UX."""
    return "".join(random.choices(string.digits, k=tamanho))

def validar_complexidade_senha(senha):
    """Exige: Mín 8 chars, 1 Maiúscula, 1 Símbolo."""
    if len(senha) < 8:
        return False
    if not re.search(r"[A-Z]", senha):
        return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", senha):
        return False
    return True

def _enviar_email_worker(destinatario, assunto, corpo_html):
    """Worker interno para disparo de e-mail SMTP via Thread."""
    # Nota: Em produção, garanta que essas variáveis estejam no seu .env
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_user = os.getenv('SMTP_USER', 'seu_email@votahub.com')
    smtp_pass = os.getenv('SMTP_PASS', 'sua_senha_de_app')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = assunto
    msg['From'] = smtp_user
    msg['To'] = destinatario
    
    msg.attach(MIMEText(corpo_html, 'html'))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destinatario, msg.as_string())
        server.quit()
        print(f"[MAILER] E-mail enviado com sucesso para {destinatario}")
    except Exception as e:
        print(f"[MAILER-ERROR] Falha ao enviar e-mail para {destinatario}: {str(e)}")

def disparar_email_assincrono(destinatario, assunto, corpo_html):
    """Dispara a thread para não bloquear a requisição HTTP do usuário (Background Task)."""
    thread = threading.Thread(target=_enviar_email_worker, args=(destinatario, assunto, corpo_html))
    thread.daemon = True
    thread.start()

# ==========================================
# ROTAS DE AUTENTICAÇÃO
# ==========================================

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Sanitização: Limpa mensagens flash vazadas de outros módulos no acesso GET
    if request.method == 'GET':
        session.pop('_flashes', None)
        return render_template('auth/login.html')

    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()

    conn = get_db_connection()
    usuario = None
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM usuarios WHERE email = %s AND status = 'ativo'", (email,))
                usuario = cursor.fetchone()
        finally:
            conn.close()

    # Bloqueio 1: Usuário inexistente
    if not usuario:
        flash('Credenciais inválidas ou usuário inativo.', 'danger')
        return render_template('auth/login.html')

    # Bloqueio 2: Validação de Hash
    if not check_password_hash(usuario['senha_hash'], password):
        flash('Credenciais inválidas.', 'danger')
        return render_template('auth/login.html')

    # Fluxo Especial: Primeiro Acesso (Double Auth / Reset)
    if usuario.get('primeiro_acesso') is True:
        codigo_2fa = gerar_codigo_verificacao_numerico()
        session['reset_code'] = codigo_2fa
        session['temp_email'] = email
        
        # Disparo de e-mail assíncrono
        html_body = f"""
        <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
            <h2 style="color: #4f46e5;">VotaHub - Verificação de Acesso</h2>
            <p>Olá, {usuario['nome']}. Identificamos que este é o seu primeiro acesso.</p>
            <p>Seu código de verificação é: <strong><span style="font-size: 24px; letter-spacing: 4px;">{codigo_2fa}</span></strong></p>
            <p>Por questões de segurança, você deverá cadastrar uma nova senha logo em seguida.</p>
        </div>
        """
        disparar_email_assincrono(email, "VotaHub - Seu Código de Acesso", html_body)
        
        # Não usamos flash() de sucesso aqui para manter a tela limpa, a UI cuidará de mostrar o modal
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    # Fluxo Padrão: Login bem-sucedido
    session.clear() # Prevenção contra Session Fixation
    session['user_id'] = usuario['id']
    session['cliente_id'] = usuario['cliente_id']
    session['role'] = usuario['role']
    session['nome'] = usuario['nome']

    # Roteamento baseado em Role
    if usuario['role'] in ['superadmin', 'admin', 'master']:
        return redirect(url_for('superadmin.painel_geral'))
    return redirect(url_for('crm.dashboard_index'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/trocar-senha', methods=['POST'])
def trocar_senha():
    email = request.form.get('email', '').strip().lower()
    codigo_digitado = request.form.get('codigo', '').strip()
    nova_senha = request.form.get('nova_senha', '').strip()

    # Validação do Código 2FA
    if codigo_digitado != session.get('reset_code'):
        flash('Código de verificação incorreto.', 'danger')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    # Validação de Segurança da Nova Senha (Backend Check)
    if not validar_complexidade_senha(nova_senha):
        flash('A senha deve ter no mínimo 8 caracteres, 1 letra maiúscula e 1 símbolo.', 'warning')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    # Persistência
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            novo_hash = generate_password_hash(nova_senha)
            cursor.execute(
                "UPDATE usuarios SET senha_hash = %s, primeiro_acesso = FALSE WHERE email = %s", 
                (novo_hash, email)
            )
        conn.commit()
        session.pop('reset_code', None)
        session.pop('temp_email', None)
        flash('Senha atualizada com sucesso! Por favor, faça o login.', 'success')
    except Exception as e:
        conn.rollback()
        flash('Ocorreu um erro interno. Tente novamente.', 'danger')
        print(f"[DB-ERROR] Erro ao trocar senha: {str(e)}")
    finally:
        if conn:
            conn.close()
            
    return redirect(url_for('auth.login'))

# Adicione isso ao seu arquivo de utilitários de e-mail (ou auth.py)
def enviar_alerta_sistema(destinatario, nome_usuario, tipo_alerta, descricao):
    assunto = f"VotaHub | Novo Alerta: {tipo_alerta}"
    
    # Design System do e-mail seguindo o padrão do Login
    html_body = f"""
    <div style="font-family: 'Inter', Arial; color: #1f2937; max-width: 600px; margin: auto; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px;">
        <h2 style="color: #4f46e5;">🚀 VotaHub Alertas</h2>
        <p>Olá, <strong>{nome_usuario}</strong>!</p>
        <div style="background-color: #f9fafb; padding: 15px; border-radius: 8px; border-left: 4px solid #4f46e5;">
            <p style="margin: 0; font-weight: bold;">{tipo_alerta}</p>
            <p style="margin: 5px 0 0 0; color: #4b5563;">{descricao}</p>
        </div>
        <p style="margin-top: 20px;">
            <a href="https://seusite.com/login" style="background-color: #4f46e5; color: white; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold;">Ver no Painel</a>
        </p>
        <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 20px 0;">
        <p style="font-size: 12px; color: #9ca3af;">Este é um e-mail automático. Não é necessário responder.</p>
    </div>
    """
    disparar_email_assincrono(destinatario, assunto, html_body)