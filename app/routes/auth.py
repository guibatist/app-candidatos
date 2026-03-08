# === BLOCO 1: DEPENDÊNCIAS E SETUP ===
import random
import string
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from psycopg2.extras import RealDictCursor

# Nossa conexão global com o PostgreSQL (Neon.tech)
from app.utils.db import get_db_connection 

auth_bp = Blueprint('auth', __name__)


# === BLOCO 2: HELPERS DE SEGURANÇA ===
def gerar_codigo_verificacao():
    """
    Gera um código de 6 caracteres: 3 Letras Maiúsculas e 3 Números aleatoriamente misturados.
    Utilizado para validação de primeiro acesso (2FA/Setup).
    """
    letras = random.choices(string.ascii_uppercase, k=3)
    numeros = random.choices(string.digits, k=3)
    codigo = letras + numeros
    random.shuffle(codigo)
    return "".join(codigo)


# === BLOCO 3: ROTAS DE AUTENTICAÇÃO E SESSÃO ===
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = get_db_connection()
        usuario = None
        if conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM usuarios WHERE email = %s AND status = 'ativo'", (email,))
                    usuario = cursor.fetchone()
            finally:
                conn.close()

        # === FASE DE VALIDAÇÃO ===
        if usuario and check_password_hash(usuario['senha_hash'], password):
            
            # 1. Tratamento de Primeiro Acesso (Segurança)
            if usuario.get('primeiro_acesso'):
                # ... (lógica do código de verificação permanece aqui)
                return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

            # 2. Configuração de Sessão (Onde o bloco entra)
            session.clear()
            session['user_id'] = usuario['id']
            session['cliente_id'] = usuario['cliente_id']
            session['role'] = usuario['role']
            session['nome'] = usuario['nome']

            # === BLOCO DE BIFURCAÇÃO (O CORAÇÃO DO SaaS) ===
            # Aqui decidimos se ele é "Dono da Plataforma" ou "Cliente da Campanha"
            
            # Lógica Master: Staff VotaHub
            if usuario['role'] in ['superadmin', 'admin', 'master']:
                return redirect(url_for('superadmin.painel_geral'))
            
            # Lógica CRM: Candidatos e Assessores
            elif usuario['role'] in ['candidato', 'assessor', 'coordenador']:
                return redirect(url_for('crm.dashboard_index'))

        # Se cair aqui, as credenciais falharam
        flash('E-mail ou senha incorretos.', 'danger')
        
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


# === BLOCO 4: RECUPERAÇÃO E PRIMEIRO ACESSO ===
@auth_bp.route('/trocar-senha', methods=['POST'])
def trocar_senha():
    email = request.form.get('email', '').strip().lower()
    codigo_digitado = request.form.get('codigo', '').strip().upper()
    nova_senha = request.form.get('nova_senha')

    # 1. Validação do Código em Sessão
    if codigo_digitado != session.get('reset_code'):
        flash('O Código de verificação está incorreto.', 'danger')
        return render_template('auth/login.html', show_reset_modal=True, temp_email=email)

    # 2. Conexão com o Banco
    conn = get_db_connection()
    if not conn:
        flash('Erro interno no servidor.', 'danger')
        return redirect(url_for('auth.login'))

    # 3. Transação de Atualização de Senha
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
        
        # Limpa as variáveis temporárias de segurança
        session.pop('reset_code', None)
        session.pop('temp_email', None)

        flash('Senha atualizada com sucesso! Faça login com a sua nova senha.', 'success')
        
    except Exception as e:
        # ROLLBACK: Se algo falhar, desfaz tudo para não corromper o banco
        conn.rollback()
        print(f"Erro Crítico ao trocar senha: {e}")
        flash('Erro de processamento ao trocar a senha. Tente novamente.', 'danger')
        
    finally:
        conn.close()

    return redirect(url_for('auth.login'))