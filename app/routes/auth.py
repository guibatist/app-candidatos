import random
import string
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from psycopg2.extras import RealDictCursor
from app.utils.db import get_db_connection 

auth_bp = Blueprint('auth', __name__)

def gerar_codigo_verificacao():
    letras = random.choices(string.ascii_uppercase, k=3)
    numeros = random.choices(string.digits, k=3)
    codigo = letras + numeros
    random.shuffle(codigo)
    return "".join(codigo)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        print(f"\n[DEBUG] Tentativa de Login: {email}") # LOG 1

        conn = get_db_connection()
        usuario = None
        if conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM usuarios WHERE email = %s AND status = 'ativo'", (email,))
                    usuario = cursor.fetchone()
            finally:
                conn.close()

        if not usuario:
            print(f"[DEBUG] Usuário {email} não encontrado ou inativo no banco.") # LOG 2
            flash('E-mail não encontrado.', 'danger')
            return render_template('auth/login.html')

        # TESTE DO HASH
        senha_bate = check_password_hash(usuario['senha_hash'], password)
        print(f"[DEBUG] Senha digitada: {password}") # LOG 3
        print(f"[DEBUG] A senha bate com o hash? {senha_bate}") # LOG 4

        if senha_bate:
            # TESTE DA FLAG DE PRIMEIRO ACESSO
            print(f"[DEBUG] Valor de primeiro_acesso no DB: {usuario.get('primeiro_acesso')} (Tipo: {type(usuario.get('primeiro_acesso'))})") # LOG 5
            
            if usuario.get('primeiro_acesso') is True:
                codigo = gerar_codigo_verificacao()
                session['reset_code'] = codigo
                session['temp_email'] = email
                
                print(f"\n{'='*50}")
                print(f"🔑 CÓDIGO GERADO: {codigo}") # LOG FINAL - TEM QUE APARECER
                print(f"{'='*50}\n")
                
                flash('Sua conta requer uma nova senha.', 'info')
                return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

            # LOGIN NORMAL
            session.clear()
            session['user_id'] = usuario['id']
            session['cliente_id'] = usuario['cliente_id']
            session['role'] = usuario['role']
            session['nome'] = usuario['nome']

            if usuario['role'] in ['superadmin', 'admin', 'master']:
                return redirect(url_for('superadmin.painel_geral'))
            return redirect(url_for('crm.dashboard_index'))

        else:
            print("[DEBUG] Falha: Senha incorreta.") # LOG 6
            flash('E-mail ou senha incorretos.', 'danger')
        
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/trocar-senha', methods=['POST'])
def trocar_senha():
    email = request.form.get('email', '').strip().lower()
    codigo_digitado = request.form.get('codigo', '').strip().upper()
    nova_senha = request.form.get('nova_senha', '').strip()

    if codigo_digitado != session.get('reset_code'):
        flash('Código incorreto.', 'danger')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            novo_hash = generate_password_hash(nova_senha)
            cursor.execute("UPDATE usuarios SET senha_hash = %s, primeiro_acesso = FALSE WHERE email = %s", (novo_hash, email))
        conn.commit()
        session.pop('reset_code', None)
        flash('Senha atualizada!', 'success')
    finally:
        conn.close()
    return redirect(url_for('auth.login'))