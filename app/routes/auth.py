import random
import string
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from psycopg2.extras import RealDictCursor

# IMPORTANTE: Confirme se o caminho do import do seu db.py está correto
from app.utils.db import get_db_connection 

auth_bp = Blueprint('auth', __name__)

def gerar_codigo_verificacao():
    """Gera um código de 6 caracteres: 3 Letras Maiúsculas e 3 Números aleatoriamente misturados"""
    letras = random.choices(string.ascii_uppercase, k=3)
    numeros = random.choices(string.digits, k=3)
    codigo = letras + numeros
    random.shuffle(codigo)
    return "".join(codigo)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        # 1. Abre conexão com o banco Votahub
        conn = get_db_connection()
        if not conn:
            flash('Erro interno: Falha ao conectar ao banco de dados.', 'danger')
            return render_template('auth/login.html')

        usuario = None
        try:
            # 2. Busca indexada e blindada contra SQL Injection (%s)
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM usuarios WHERE email = %s AND status = 'ativo'", (email,))
                usuario = cursor.fetchone()
        except Exception as e:
            print(f"Erro na query de login: {e}")
        finally:
            conn.close()

        # 3. Validação de senha usando a coluna 'senha_hash'
        if usuario and check_password_hash(usuario['senha_hash'], password):
            
            # --- TRAVA DE SEGURANÇA: PRIMEIRO ACESSO ---
            if usuario.get('primeiro_acesso'):
                codigo = gerar_codigo_verificacao()
                session['reset_code'] = codigo
                session['temp_email'] = email
                
                print(f"\n{'='*50}")
                print(f"📧 E-MAIL ENVIADO PARA: {email}")
                print(f"🔑 CÓDIGO DE SEGURANÇA: {codigo}")
                print(f"{'='*50}\n")
                
                flash('Sua conta é nova! Enviamos um código de segurança para o seu e-mail.', 'info')
                return render_template('auth/login.html', show_reset_modal=True, temp_email=email)
            
            # --- LOGIN NORMAL ---
            session.clear()
            session['user_id'] = usuario.get('id')
            session['cliente_id'] = usuario.get('cliente_id')
            session['role'] = usuario.get('role')
            session['nome'] = usuario.get('nome')

            if usuario.get('role') == 'superadmin':
                return redirect(url_for('superadmin.painel_geral'))
            return redirect(url_for('crm.dashboard_index'))
        
        flash('E-mail ou senha incorretos.', 'danger')
        return render_template('auth/login.html')
        
    return render_template('auth/login.html')

@auth_bp.route('/trocar-senha', methods=['POST'])
def trocar_senha():
    email = request.form.get('email', '').strip().lower()
    codigo_digitado = request.form.get('codigo', '').strip().upper()
    nova_senha = request.form.get('nova_senha')

    if codigo_digitado != session.get('reset_code'):
        flash('O Código de verificação está incorreto.', 'danger')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    conn = get_db_connection()
    if not conn:
        flash('Erro interno no servidor.', 'danger')
        return redirect(url_for('auth.login'))

    try:
        with conn.cursor() as cursor:
            novo_hash = generate_password_hash(nova_senha)
            # Atualiza a senha e destrava a conta simultaneamente
            cursor.execute("""
                UPDATE usuarios 
                SET senha_hash = %s, primeiro_acesso = FALSE 
                WHERE email = %s
            """, (novo_hash, email))
        
        # COMMIT: Confirma a gravação no banco
        conn.commit()
        
        session.pop('reset_code', None)
        session.pop('temp_email', None)

        flash('Senha atualizada com sucesso! Faça login com a sua nova senha.', 'success')
    except Exception as e:
        # ROLLBACK: Se algo falhar, desfaz tudo para não corromper o banco
        conn.rollback()
        print(f"Erro Crítico ao trocar senha: {e}")
        flash('Erro de validação. Tente novamente.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))