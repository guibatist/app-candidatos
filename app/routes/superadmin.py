import uuid
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from psycopg2.extras import RealDictCursor

# Nossos módulos
from app.utils.db import get_db_connection
from ..services.crm_service import CRMService

# Importação da função assíncrona de e-mail do auth.py
try:
    from .auth import disparar_email_assincrono
except ImportError:
    def disparar_email_assincrono(destinatario, assunto, corpo_html):
        print(f"[MAILER-MOCK] Falha ao importar disparador. E-mail retido: {destinatario}")

superadmin_bp = Blueprint('superadmin', __name__)

# ==========================================
# BLOCO 1: HELPERS GLOBAIS E SEGURANÇA
# ==========================================

def is_superadmin():
    """Verifica rigorosamente se o usuário logado tem privilégios Master/SaaS."""
    role = session.get('role')
    return role in ['superadmin', 'master']

def _executar_re_onboarding(usuario_id, novo_email, nome):
    """
    Função interna: Quando um e-mail é alterado, o usuário original nunca recebeu a senha.
    Isso reseta a conta e dispara o convite novamente.
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
# BLOCO 2: DASHBOARD DO MASTER
# ==========================================

@superadmin_bp.route('/dashboard')
def painel_geral():
    if not is_superadmin():
        flash('Acesso restrito. Área administrativa.', 'danger')
        return redirect(url_for('auth.login'))
    
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


# ==========================================
# BLOCO 3: GESTÃO DE TENANTS (CRIAR CAMPANHAS)
# ==========================================

@superadmin_bp.route('/campanhas/nova', methods=['POST'])
def criar_campanha_completa():
    """Provisiona uma nova Campanha COM TODOS OS DADOS e dispara o onboarding."""
    if not is_superadmin(): 
        return redirect(url_for('auth.login'))
    
    # 1. Captura de Payload Absoluta
    nome_completo = request.form.get('nome_completo', '').strip()
    email_candidato = request.form.get('email_candidato', '').strip().lower()
    cargo = request.form.get('cargo', '').strip()
    partido_sigla = request.form.get('partido_sigla', '').strip().upper()
    partido_numero = request.form.get('partido_numero', '').strip()
    cpf = request.form.get('cpf', '').strip()
    telefone = request.form.get('telefone', '').strip()
    sexo = request.form.get('sexo', '').strip()
    idade = request.form.get('idade', '').strip()
    
    campanha_id = f"camp_{uuid.uuid4().hex[:10]}"
    usuario_id = f"usr_{uuid.uuid4().hex[:10]}"
    
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Insere a Campanha mapeando Partido e Sigla desde o Início
            cursor.execute("""
                INSERT INTO clientes (id, nome_candidato, cargo_disputado, partido_sigla, partido_numero, status) 
                VALUES (%s, %s, %s, %s, %s, 'ativo')
            """, (campanha_id, nome_completo, cargo, partido_sigla, partido_numero))
            
            # Insere o Usuário mapeando CPF, Telefone e Demografia
            cursor.execute("""
                INSERT INTO usuarios (id, cliente_id, nome, email, senha_hash, role, primeiro_acesso, cpf, telefone, sexo, idade)
                VALUES (%s, %s, %s, %s, %s, 'candidato', TRUE, %s, %s, %s, %s)
            """, (usuario_id, campanha_id, nome_completo, email_candidato, senha_hash, cpf, telefone, sexo, idade or None))
            
        conn.commit()
        
        # Disparo do Onboarding
        corpo_email = f"""
        <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
            <h2 style="color: #4f46e5;">Bem-vindo ao VotaHub!</h2>
            <p>Olá, <strong>{nome_completo}</strong>. Sua campanha foi provisionada com sucesso.</p>
            <p>Você já pode acessar nossa plataforma estratégica.</p>
            <div style="background-color: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0;"><strong>E-mail:</strong> {email_candidato}</p>
                <p style="margin: 5px 0 0 0;"><strong>Senha Provisória:</strong> <span style="color: #e63946;">{senha_provisoria}</span></p>
            </div>
            <p><small>Por segurança, será exigida a troca desta senha no seu primeiro acesso e a confirmação em duas etapas (2FA).</small></p>
        </div>
        """
        disparar_email_assincrono(email_candidato, "Bem-vindo ao VotaHub - Suas Credenciais", corpo_email)
        
        flash('Campanha configurada com sucesso e convite enviado ao candidato.', 'success')
        return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))
        
    except Exception as e:
        conn.rollback()
        print(f"[DB-ERROR] Erro ao criar campanha integral: {str(e)}")
        flash('Erro ao provisionar a base de dados do cliente.', 'danger')
        return redirect(url_for('superadmin.painel_geral'))
    finally:
        conn.close()

@superadmin_bp.route('/campanhas/<campanha_id>')
def perfil_campanha(campanha_id):
    if not is_superadmin(): return redirect(url_for('auth.login'))
    
    dados = CRMService.get_detalhes_campanha_completa(campanha_id)
    if not dados:
        flash('Campanha não encontrada.', 'danger')
        return redirect(url_for('superadmin.painel_geral'))
        
    return render_template('superadmin/perfil_campanha.html', 
                           campanha=dados['campanha'], 
                           candidato=dados['candidato'], 
                           assessores=dados['assessores'])


# ==========================================
# BLOCO 4: GESTÃO MESTRE DE USUÁRIOS E EDIÇÃO
# ==========================================

@superadmin_bp.route('/campanhas/<campanha_id>/usuario/salvar', methods=['POST'])
def salvar_usuario_campanha(campanha_id):
    """Cria ou edita um usuário, detectando alterações de e-mail para reenvio de credenciais."""
    if not is_superadmin(): 
        return redirect(url_for('auth.login'))
    
    usuario_id = request.form.get('usuario_id')
    role = request.form.get('role', 'assessor')
    nome = request.form.get('nome', '').strip()
    novo_email = request.form.get('email', '').strip().lower()
    
    # 1. Busca o e-mail atual no banco para checar se houve mudança
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

    # 2. Roteamento de Salvamento
    if role == 'candidato':
        sucesso = CRMService.salvar_dados_mestre_campanha(campanha_id, request.form)
        if sucesso: 
            flash('Dados mestre da campanha atualizados.', 'success')
            # Gatilho de Mudança de E-mail
            if email_antigo and email_antigo != novo_email:
                _executar_re_onboarding(usuario_id, novo_email, nome)
                flash('O e-mail foi alterado. Um novo convite de acesso foi disparado.', 'info')
        else: 
            flash('Erro ao atualizar dados da campanha.', 'danger')
            
        return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

    # 3. Lógica para Assessores (Equipe)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not usuario_id: # NOVO ASSESSOR
                uid = f"usr_{uuid.uuid4().hex[:10]}"
                senha_provisoria = "mudar@votahub"
                senha_hash = generate_password_hash(senha_provisoria)
                
                cursor.execute("""
                    INSERT INTO usuarios (id, cliente_id, nome, email, role, senha_hash, primeiro_acesso, cpf, telefone)
                    VALUES (%s, %s, %s, %s, 'assessor', %s, TRUE, %s, %s)
                """, (uid, campanha_id, nome, novo_email, senha_hash, request.form.get('cpf'), request.form.get('telefone')))
                
                corpo_email = f"""
                <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
                    <h2 style="color: #4f46e5;">Você foi adicionado à equipe!</h2>
                    <p>Olá, <strong>{nome}</strong>. Um administrador concedeu a você acesso ao VotaHub.</p>
                    <div style="background-color: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                        <p style="margin: 0;"><strong>E-mail:</strong> {novo_email}</p>
                        <p style="margin: 5px 0 0 0;"><strong>Senha Provisória:</strong> <span style="color: #e63946;">{senha_provisoria}</span></p>
                    </div>
                </div>
                """
                disparar_email_assincrono(novo_email, "Convite para Equipe VotaHub", corpo_email)
                flash('Assessor adicionado e convite disparado.', 'success')
                
            else: # EDIÇÃO DE ASSESSOR
                cursor.execute("""
                    UPDATE usuarios SET nome=%s, email=%s, cpf=%s, sexo=%s, idade=%s, telefone=%s
                    WHERE id=%s AND cliente_id=%s
                """, (nome, novo_email, request.form.get('cpf'), request.form.get('sexo'), 
                      request.form.get('idade') or None, request.form.get('telefone'),
                      usuario_id, campanha_id))
                flash('Dados do assessor atualizados.', 'success')
                
        conn.commit()
        
        # Gatilho de Mudança de E-mail para Assessor
        if usuario_id and email_antigo and email_antigo != novo_email:
            _executar_re_onboarding(usuario_id, novo_email, nome)
            flash('O e-mail foi corrigido e uma nova credencial foi enviada.', 'info')
            
    except Exception as e:
        conn.rollback()
        print(f"[DB-ERROR] Erro ao salvar assessor: {e}")
        flash('Erro interno ao salvar dados do usuário.', 'danger')
    finally:
        conn.close()
        
    return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

@superadmin_bp.route('/usuarios/<usuario_id>/reset-senha', methods=['POST'])
def resetar_senha_usuario(usuario_id):
    """Força o reset de senha para o padrão do sistema."""
    if not is_superadmin(): return redirect(url_for('auth.login'))
    
    campanha_id = request.form.get('campanha_id')
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        # A CORREÇÃO ESTÁ AQUI: Adicionado o cursor_factory=RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                UPDATE usuarios 
                SET senha_hash = %s, primeiro_acesso = TRUE 
                WHERE id = %s RETURNING email, nome
            """, (senha_hash, usuario_id))
            usuario = cursor.fetchone()
            
        if usuario:
            conn.commit()
            corpo_email = f"""
            <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
                <h2 style="color: #4f46e5;">Reset de Senha Solicitado</h2>
                <p>Olá, {usuario['nome']}. O administrador da plataforma resetou sua senha de acesso.</p>
                <p>Sua nova senha provisória é: <strong>{senha_provisoria}</strong></p>
                <p>Você será obrigado a trocá-la no próximo login.</p>
            </div>
            """
            disparar_email_assincrono(usuario['email'], "VotaHub - Reset de Senha", corpo_email)
            flash('Senha resetada para o padrão e usuário notificado.', 'success')
        else:
            flash('Usuário não encontrado.', 'warning')
            
    except Exception as e:
        conn.rollback()
        print(f"[DB-ERROR] Erro no reset de senha: {e}")
        flash('Falha ao processar o reset.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

@superadmin_bp.route('/usuarios/<usuario_id>/excluir', methods=['POST'])
def excluir_usuario(usuario_id):
    """Revoga o acesso excluindo permanentemente o usuário."""
    if not is_superadmin(): return redirect(url_for('auth.login'))
        
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM usuarios WHERE id = %s", (str(usuario_id),))
            conn.commit()
            flash('Acesso revogado permanentemente no sistema.', 'warning')
        except Exception as e:
            conn.rollback()
            print(f"[DB-ERROR] Erro SQL ao excluir usuário: {e}")
            flash('Falha ao tentar remover as credenciais do usuário.', 'danger')
        finally:
            conn.close()
    
    return redirect(request.referrer or url_for('superadmin.painel_geral'))