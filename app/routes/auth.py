import os
import json
import random
import string
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint('auth', __name__)

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH_USUARIOS = os.path.join(base_dir, 'data', 'usuarios.json')

def load_usuarios():
    if os.path.exists(PATH_USUARIOS):
        with open(PATH_USUARIOS, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
    return []

def save_usuarios(usuarios):
    with open(PATH_USUARIOS, 'w', encoding='utf-8') as f:
        json.dump(usuarios, f, indent=4, ensure_ascii=False)

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

        usuarios = load_usuarios()
        usuario = next((u for u in usuarios if u.get('email', '').lower() == email), None)

        if usuario and check_password_hash(usuario['senha'], password):
            
            # --- TRAVA DE SEGURANÇA: PRIMEIRO ACESSO ---
            if usuario.get('precisa_trocar_senha'):
                codigo = gerar_codigo_verificacao()
                session['reset_code'] = codigo
                session['temp_email'] = email
                
                # SIMULADOR DE DISPARO DE E-MAIL (Vai aparecer no seu Terminal)
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
    email = request.form.get('email')
    codigo_digitado = request.form.get('codigo', '').strip().upper()
    nova_senha = request.form.get('nova_senha')

    if codigo_digitado != session.get('reset_code'):
        flash('O Código de verificação está incorreto.', 'danger')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    usuarios = load_usuarios()
    usuario = next((u for u in usuarios if u.get('email', '').lower() == email.lower()), None)

    if usuario:
        # Grava a nova senha com Hash Forte e remove a trava
        usuario['senha'] = generate_password_hash(nova_senha)
        usuario['precisa_trocar_senha'] = False
        save_usuarios(usuarios)

        # Limpa o lixo da sessão
        session.pop('reset_code', None)
        session.pop('temp_email', None)

        flash('Senha atualizada com sucesso! Faça login com a sua nova senha.', 'success')
        return redirect(url_for('auth.login'))
    
    flash('Erro de validação. Tente novamente.', 'danger')
    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))