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
from email.message import EmailMessage

load_dotenv()
from app.utils.mailer import Mailer
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
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_user = os.getenv('SMTP_USER', 'seu_email@votahub.com') # Puxa do .env
    smtp_pass = os.getenv('SMTP_PASS', 'sua_senha_de_app')      # Puxa do .env

    # Usando a biblioteca moderna do Python 3
    msg = EmailMessage()
    msg['Subject'] = assunto
    msg['From'] = smtp_user
    msg['To'] = destinatario
    
    # Isso aqui blinda o código contra qualquer erro de acentuação (UTF-8)
    msg.set_content(corpo_html, subtype='html', charset='utf-8')

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        # Atenção: Mudamos de sendmail para send_message
        server.send_message(msg) 
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
    # Sanitização: Limpa mensagens flash vazadas no acesso GET
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
                # Busca usuário ativo
                cursor.execute("SELECT * FROM usuarios WHERE email = %s AND status = 'ativo'", (email,))
                usuario = cursor.fetchone()
        finally:
            conn.close()

    # Validação Básica
    if not usuario or not check_password_hash(usuario['senha_hash'], password):
        flash('Credenciais inválidas ou usuário inativo.', 'danger')
        return render_template('auth/login.html')

    # ================================================================
    # FLUXO DE PRIMEIRO ACESSO: Dispara código de segurança (2FA)
    # ================================================================
    if usuario.get('primeiro_acesso') is True:
        codigo_2fa = gerar_codigo_verificacao_numerico()
        session['reset_code'] = codigo_2fa
        session['temp_email'] = email
        
        try:
            # Chamada ao Mailer usando o template 'emails/codigo_2fa.html'
            Mailer.enviar_codigo_2fa(email, usuario['nome'], codigo_2fa)
        except Exception as e:
            print(f"🚨 [MAIL-ERROR] Erro ao enviar código 2FA: {e}")
            flash('Erro ao enviar código de verificação por e-mail.', 'warning')
        
        # Abre o modal de reset no front-end
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    # ================================================================
    # FLUXO PADRÃO: Login Direto (Usuários já ativados)
    # ================================================================
    session.clear() # Segurança contra Session Fixation
    session['user_id'] = usuario['id']
    session['cliente_id'] = usuario['cliente_id']
    session['role'] = usuario['role']
    session['nome'] = usuario['nome']

    # Redirecionamento baseado no nível de acesso
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

    # 1. Validação do Código 2FA
    if codigo_digitado != session.get('reset_code'):
        flash('Código de verificação incorreto.', 'danger')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    # 2. Validação de Segurança da Nova Senha
    if not validar_complexidade_senha(nova_senha):
        flash('A senha deve ter no mínimo 8 caracteres, 1 letra maiúscula e 1 símbolo.', 'warning')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    # 3. Persistência e Gatilho de Boas-Vindas
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Pegamos o nome antes de atualizar, para usar no e-mail
            cursor.execute("SELECT nome FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
            
            if not usuario:
                flash('Usuário não encontrado.', 'danger')
                return redirect(url_for('auth.login'))

            novo_hash = generate_password_hash(nova_senha)
            
            # Atualiza a senha e desativa a trava de primeiro acesso
            cursor.execute(
                "UPDATE usuarios SET senha_hash = %s, primeiro_acesso = FALSE WHERE email = %s", 
                (novo_hash, email)
            )
            
        conn.commit()
        
        # ================================================================
        # GATILHO DO E-MAIL DE BOAS-VINDAS + MANUAL
        # ================================================================
        try:
            # Agora que o banco confirmou a troca, mandamos o manual
            Mailer.enviar_boas_vindas_manual(email, usuario['nome'])
        except Exception as mail_err:
            print(f"🚨 [MAIL-ERROR] Falha ao enviar manual de boas-vindas: {mail_err}")
            # Não damos flash de erro aqui para não confundir o usuário, 
            # já que a senha dele FOI trocada com sucesso.

        # Limpeza de sessão
        session.pop('reset_code', None)
        session.pop('temp_email', None)
        
        flash('Senha atualizada com sucesso! Verifique seu e-mail para acessar o manual do sistema.', 'success')
        
    except Exception as e:
        if conn: conn.rollback()
        flash('Ocorreu um erro interno. Tente novamente.', 'danger')
        print(f"[DB-ERROR] Erro ao trocar senha: {str(e)}")
    finally:
        if conn:
            conn.close()
            
    return redirect(url_for('auth.login'))

def enviar_alerta_sistema(destinatario, nome_usuario, tipo_alerta, descricao):
    """
    Dispara alertas genéricos do sistema utilizando o novo padrão de layout base
    e envio assíncrono.
    """
    from flask import render_template
    from app.utils.mailer import Mailer
    from app.routes.auth import disparar_email_assincrono
    
    # 1. Gera o ID curto para não empilhar no Gmail
    protocolo = Mailer.gerar_protocolo()
    
    # 2. Monta o assunto padronizado
    assunto = f"{tipo_alerta} [Ref: #{protocolo}]"
    
    # 3. Injeta os dados no template HTML
    html = render_template(
        'emails/alerta_sistema.html',
        nome_usuario=nome_usuario,
        tipo_alerta=tipo_alerta,
        descricao=descricao,
        protocolo=protocolo
    )
    
    # 4. Envia o e-mail em background sem travar a tela do usuário
    disparar_email_assincrono(destinatario, assunto, html)