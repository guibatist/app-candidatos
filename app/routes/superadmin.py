import uuid
import secrets
from functools import wraps
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash
from psycopg2.extras import RealDictCursor

# 1. Definição ÚNICA do Blueprint
superadmin_bp = Blueprint('superadmin', __name__)

# Nossos módulos
from app.utils.db import get_db_connection
from app.services.crm_service import CRMService

# Importação da função assíncrona de e-mail do auth.py
try:
    from app.routes.auth import disparar_email_assincrono # Ajuste o caminho se necessário
except ImportError:
    def disparar_email_assincrono(destinatario, assunto, corpo_html):
        print(f"[MAILER-MOCK] Falha ao importar disparador. E-mail retido: {destinatario}")

# ==========================================
# BLOCO 1: HELPERS GLOBAIS E SEGURANÇA
# ==========================================

def is_superadmin():
    """Verifica rigorosamente se o usuário logado tem privilégios Master/SaaS."""
    role = session.get('role')
    return role in ['superadmin', 'master']

def login_required(f):
    """Decorador de segurança para rotas administrativas."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, faça login para acessar.', 'warning')
            return redirect(url_for('auth.login')) # Ajuste o nome da sua rota de login
        if not is_superadmin():
            return "Acesso Negado. Área restrita a Administradores do Sistema.", 403
        return f(*args, **kwargs)
    return decorated_function

def _executar_re_onboarding(usuario_id, novo_email, nome):
    """
    Quando um e-mail é alterado, reseta a conta e dispara o convite novamente.
    """
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE usuarios 
                SET senha_hash = %s, primeiro_acesso = TRUE 
                WHERE id = %s
            """, (senha_hash, usuario_id))
        conn.commit()
        
        corpo_email = f"""
        <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
            <h2 style="color: #4f46e5;">Atualização de Acesso - VotaHub</h2>
            <p>Olá, <strong>{nome}</strong>. Seu e-mail de acesso foi atualizado/corrigido por um administrador.</p>
            <div style="background-color: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0;"><strong>Novo E-mail:</strong> {novo_email}</p>
                <p style="margin: 5px 0 0 0;"><strong>Senha Provisória:</strong> <span style="color: #e63946;">{senha_provisoria}</span></p>
            </div>
            <p><small>Por segurança, será exigida a troca desta senha no seu primeiro acesso.</small></p>
        </div>
        """
        disparar_email_assincrono(novo_email, "Suas Novas Credenciais - VotaHub", corpo_email)
        return True
    except Exception as e:
        if conn: conn.rollback()
        print(f"[DB-ERROR] Erro no Re-Onboarding: {e}")
        return False
    finally:
        if conn: conn.close()


# ==========================================
# BLOCO 2: DASHBOARD E LISTAGENS
# ==========================================

@superadmin_bp.route('/dashboard')
@login_required
def painel_geral():
    conn = get_db_connection()
    campanhas = []
    
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM clientes ORDER BY created_at DESC")
                campanhas = cursor.fetchall()
                
                cursor.execute("SELECT id, cliente_id, nome, email, role, primeiro_acesso FROM usuarios")
                todos_usuarios = cursor.fetchall()
                
                for camp in campanhas:
                    camp['usuarios'] = [u for u in todos_usuarios if u['cliente_id'] == camp['id']]
                    
        except Exception as e:
            print(f"[DB-ERROR] Erro ao carregar Dashboard Master: {e}")
            flash('Erro ao carregar os dados do sistema.', 'danger')
        finally:
            conn.close()

    permissoes_master = {"permite_mapa": True, "permite_equipe": True, "permite_bi": True}
    return render_template('superadmin/dashboard.html', campanhas=campanhas, permissoes=permissoes_master)


@superadmin_bp.route('/clientes')
@login_required
def listar_clientes():
    """Lista de clientes para gestão de Tokens de API (VotoImpacto)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Pegamos nome_candidato da tabela clientes (conforme seu banco real)
            cursor.execute("SELECT id, nome_candidato as nome, email, api_token FROM clientes ORDER BY nome_candidato ASC")
            clientes = cursor.fetchall()
            return render_template('superadmin/clientes.html', clientes=clientes)
    except Exception as e:
        print(f"[DB-ERROR] Erro ao listar clientes: {e}")
        flash('Erro ao listar os clientes.', 'danger')
        return redirect(url_for('superadmin.painel_geral'))
    finally:
        if conn: conn.close()


@superadmin_bp.route('/gerar-token/<cliente_id>', methods=['POST'])
@login_required
def gerar_novo_token(cliente_id):
    """Gera um novo token de integração de site para o cliente."""
    novo_token = secrets.token_hex(16) 
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE clientes SET api_token = %s WHERE id = %s", (novo_token, cliente_id))
            conn.commit()
        return jsonify({'sucesso': True, 'token': novo_token})
    except Exception as e:
        print(f"[DB-ERROR] Erro ao gerar token: {e}")
        return jsonify({'sucesso': False}), 500
    finally:
        if conn: conn.close()


# ==========================================
# BLOCO 3: GESTÃO DE TENANTS (CRIAR CAMPANHAS)
# ==========================================



@superadmin_bp.route('/campanhas/<campanha_id>')
@login_required
def perfil_campanha(campanha_id):
    dados = CRMService.get_detalhes_campanha_completa(campanha_id)
    if not dados:
        flash('Campanha não encontrada.', 'danger')
        return redirect(url_for('superadmin.painel_geral'))
        
    return render_template('superadmin/perfil_campanha.html', 
                           campanha=dados['campanha'], 
                           candidato=dados['candidato'], 
                           assessores=dados['assessores'])

# ==========================================
# BLOCO 4: AÇÕES MESTRES DE USUÁRIOS
# ==========================================

@superadmin_bp.route('/campanhas/nova', methods=['POST'])
@login_required
def criar_campanha_completa():
    # Captura os dados básicos
    nome_completo = request.form.get('nome_completo', '').strip()
    email_candidato = request.form.get('email_candidato', '').strip().lower()
    cargo = request.form.get('cargo', '').strip()
    partido_sigla = request.form.get('partido_sigla', '').strip().upper()
    partido_numero = request.form.get('partido_numero', '').strip()
    
    # Tratamento para opcionais
    cpf = request.form.get('cpf', '').strip() or None
    telefone = request.form.get('telefone', '').strip() or None
    sexo = request.form.get('sexo', '').strip() or None
    
    # Tratamento rigoroso para Idade
    idade_raw = request.form.get('idade', '').strip()
    idade_final = int(idade_raw) if idade_raw.isdigit() else None
    
    # Gerações de chaves
    campanha_id = f"camp_{uuid.uuid4().hex[:10]}"
    usuario_id = f"usr_{uuid.uuid4().hex[:10]}"
    api_token = secrets.token_hex(16)
    
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Cria a campanha com o token de site
            cursor.execute("""
                INSERT INTO clientes (id, nome_candidato, cargo_disputado, partido_sigla, partido_numero, status, api_token) 
                VALUES (%s, %s, %s, %s, %s, 'ativo', %s)
            """, (campanha_id, nome_completo, cargo, partido_sigla, partido_numero, api_token))
            
            # 2. Cria o usuário com TODOS OS DADOS TRATADOS
            cursor.execute("""
                INSERT INTO usuarios (id, cliente_id, nome, email, senha_hash, role, primeiro_acesso, cpf, telefone, sexo, idade)
                VALUES (%s, %s, %s, %s, %s, 'candidato', TRUE, %s, %s, %s, %s)
            """, (usuario_id, campanha_id, nome_completo, email_candidato, senha_hash, cpf, telefone, sexo, idade_final))
            
        conn.commit()
        
        # ==========================================
        # O CÓDIGO DO E-MAIL VOLTOU AQUI
        # ==========================================
        corpo_email = f"""
        <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
            <h2 style="color: #8b5cf6;">Bem-vindo ao VotoImpacto!</h2>
            <p>Olá, <strong>{nome_completo}</strong>. Sua campanha foi provisionada com sucesso.</p>
            <p>Sua plataforma estratégica inteligente já está pronta para uso.</p>
            <div style="background-color: #f8fafc; border-left: 4px solid #8b5cf6; padding: 15px; border-radius: 4px; margin: 20px 0;">
                <p style="margin: 0;"><strong>E-mail de Acesso:</strong> {email_candidato}</p>
                <p style="margin: 5px 0 0 0;"><strong>Senha Provisória:</strong> <span style="color: #e63946;">{senha_provisoria}</span></p>
            </div>
            <p><small>Por segurança, será exigida a troca desta senha no seu primeiro acesso.</small></p>
        </div>
        """
        
        try:
            disparar_email_assincrono(email_candidato, "Bem-vindo ao VotoImpacto - Credenciais", corpo_email)
            flash('Campanha configurada e e-mail enviado com sucesso!', 'success')
        except Exception as mail_error:
            print(f"[MAIL-ERROR] Falha ao enviar email: {mail_error}")
            flash('Campanha criada, mas houve um erro ao enviar o e-mail.', 'warning')
            
        return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))
        
    except Exception as e:
        if conn: conn.rollback()
        if 'usuarios_cpf_key' in str(e):
            flash('Este CPF já está cadastrado em outra conta.', 'danger')
        else:
            flash('Erro ao provisionar a base de dados do cliente.', 'danger')
        print(f"[DB-CRITICAL] Erro ao criar campanha: {e}") 
        return redirect(url_for('superadmin.painel_geral'))
    finally:
        if conn: conn.close()

@superadmin_bp.route('/campanhas/<campanha_id>/usuario/salvar', methods=['POST'])
@login_required
def salvar_usuario_campanha(campanha_id):
    """Cria ou edita um usuário, detectando alterações de e-mail para reenvio de credenciais."""
    usuario_id = request.form.get('usuario_id')
    role = request.form.get('role', 'assessor')
    nome = request.form.get('nome', '').strip()
    novo_email = request.form.get('email', '').strip().lower()
    
    email_antigo = None
    if usuario_id:
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT email FROM usuarios WHERE id = %s", (usuario_id,))
                user_db = cursor.fetchone()
                if user_db: email_antigo = user_db['email']
        finally:
            if conn: conn.close()

    if role == 'candidato':
        sucesso = CRMService.salvar_dados_mestre_campanha(campanha_id, request.form)
        if sucesso: 
            flash('Dados mestre da campanha atualizados.', 'success')
            if email_antigo and email_antigo != novo_email:
                _executar_re_onboarding(usuario_id, novo_email, nome)
                flash('O e-mail foi alterado. Um novo convite foi disparado.', 'info')
        else: 
            flash('Erro ao atualizar dados.', 'danger')
        return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not usuario_id:
                uid = f"usr_{uuid.uuid4().hex[:10]}"
                senha_provisoria = "mudar@votahub"
                senha_hash = generate_password_hash(senha_provisoria)
                
                cursor.execute("""
                    INSERT INTO usuarios (id, cliente_id, nome, email, role, senha_hash, primeiro_acesso, cpf, telefone)
                    VALUES (%s, %s, %s, %s, 'assessor', %s, TRUE, %s, %s)
                """, (uid, campanha_id, nome, novo_email, senha_hash, request.form.get('cpf'), request.form.get('telefone')))
                flash('Assessor adicionado e convite disparado.', 'success')
            else:
                cursor.execute("""
                    UPDATE usuarios SET nome=%s, email=%s, cpf=%s, sexo=%s, idade=%s, telefone=%s
                    WHERE id=%s AND cliente_id=%s
                """, (nome, novo_email, request.form.get('cpf'), request.form.get('sexo'), 
                      request.form.get('idade') or None, request.form.get('telefone'),
                      usuario_id, campanha_id))
                flash('Dados atualizados.', 'success')
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        flash('Erro interno ao salvar.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

@superadmin_bp.route('/usuarios/<usuario_id>/reset-senha', methods=['POST'])
@login_required
def resetar_senha_usuario(usuario_id):
    """Força o reset de senha para o padrão do sistema E ENVIA O E-MAIL."""
    campanha_id = request.form.get('campanha_id')
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # O 'RETURNING email, nome' pega os dados na mesma hora que atualiza a senha
            cursor.execute("""
                UPDATE usuarios 
                SET senha_hash = %s, primeiro_acesso = TRUE 
                WHERE id = %s RETURNING email, nome
            """, (senha_hash, usuario_id))
            usuario = cursor.fetchone()
            
        if usuario:
            conn.commit()
            
            # ==========================================
            # DISPARO DO E-MAIL DE RESET (O que faltava!)
            # ==========================================
            corpo_email = f"""
            <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
                <h2 style="color: #8b5cf6;">Acesso Redefinido - VotoImpacto</h2>
                <p>Olá, <strong>{usuario['nome']}</strong>. O administrador redefiniu seu acesso.</p>
                <div style="background-color: #f8fafc; border-left: 4px solid #8b5cf6; padding: 15px; border-radius: 4px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>E-mail de Acesso:</strong> {usuario['email']}</p>
                    <p style="margin: 5px 0 0 0;"><strong>Nova Senha Provisória:</strong> <span style="color: #e63946;">{senha_provisoria}</span></p>
                </div>
                <p><small>Por segurança, você deverá trocar essa senha ao fazer login.</small></p>
            </div>
            """
            
            try:
                # Certifique-se de que a função disparar_email_assincrono está importada no topo do arquivo!
                disparar_email_assincrono(usuario['email'], "VotoImpacto - Novo Acesso", corpo_email)
                flash('Senha resetada e e-mail enviado com sucesso!', 'success')
            except Exception as mail_err:
                print(f"[MAIL-ERROR] Erro ao enviar reset: {mail_err}")
                flash('Senha resetada no banco, mas o e-mail falhou.', 'warning')
                
        else:
            flash('Usuário não encontrado.', 'warning')
    except Exception as e:
        if conn: conn.rollback()
        flash('Falha ao processar reset.', 'danger')
        print(f"[DB-ERROR] Erro no reset de senha: {e}")
    finally:
        if conn: conn.close()
        
    return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))


@superadmin_bp.route('/usuarios/<usuario_id>/excluir', methods=['POST'])
@login_required
def excluir_usuario(usuario_id):
    """Revoga o acesso excluindo permanentemente o usuário."""
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM usuarios WHERE id = %s", (str(usuario_id),))
            conn.commit()
            flash('Acesso revogado.', 'warning')
        except Exception as e:
            if conn: conn.rollback()
            flash('Falha ao excluir usuário.', 'danger')
        finally:
            conn.close()
    
    return redirect(request.referrer or url_for('superadmin.painel_geral'))

# ==========================================
# BLOCO 5: CENTRAL DE CHAMADOS (MASTER)
# ==========================================

@superadmin_bp.route('/chamados')
@login_required
def listar_chamados():
    conn = get_db_connection()
    chamados = []
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT c.*, u.nome as usuario_nome, cl.nome_candidato as cliente_nome
                    FROM chamados_suporte c
                    JOIN usuarios u ON c.usuario_id = u.id
                    JOIN clientes cl ON c.cliente_id = cl.id
                    ORDER BY 
                        CASE WHEN c.status = 'Aberto' THEN 1 WHEN c.status = 'Em Análise' THEN 2 ELSE 3 END,
                        c.criado_em DESC
                """)
                chamados = cursor.fetchall()
        except Exception as e:
            print(f"[DB-ERROR] Erro ao carregar chamados: {e}")
        finally:
            conn.close()
            
    return render_template('superadmin/chamados.html', chamados=chamados)

@superadmin_bp.route('/chamados/<chamado_id>/atualizar', methods=['POST'])
@login_required
def atualizar_chamado(chamado_id):
    status = request.form.get('status')
    resposta = request.form.get('resposta_admin')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE chamados_suporte 
                SET status = %s, resposta_admin = %s, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (status, resposta, chamado_id))
        conn.commit()
        flash('Chamado atualizado.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('Erro ao atualizar chamado.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('superadmin.listar_chamados'))