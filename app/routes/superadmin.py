import uuid
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from psycopg2.extras import RealDictCursor

# Nossos módulos
from app.utils.db import get_db_connection
from ..services.crm_service import CRMService

# Importação da função assíncrona de e-mail criada no auth.py
try:
    from .auth import disparar_email_assincrono
except ImportError:
    # Fallback seguro caso a estrutura de pastas exija outro caminho de import
    def disparar_email_assincrono(destinatario, assunto, corpo_html):
        print(f"[MAILER-MOCK] E-mail para {destinatario} não importado corretamente. Assunto: {assunto}")

superadmin_bp = Blueprint('superadmin', __name__)

# ==========================================
# BLOCO 1: HELPERS DE SEGURANÇA GLOBAIS
# ==========================================

def is_superadmin():
    """Verifica rigorosamente se o usuário logado tem privilégios Master/SaaS."""
    role = session.get('role')
    return role in ['superadmin', 'master']


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
                # Busca as campanhas
                cursor.execute("SELECT * FROM clientes ORDER BY created_at DESC")
                campanhas = cursor.fetchall()
                
                # Busca os usuários
                cursor.execute("SELECT id, cliente_id, nome, email, role, primeiro_acesso FROM usuarios")
                todos_usuarios = cursor.fetchall()
                
                # Agrupamento em memória para evitar queries dentro de loop (Otimização)
                for camp in campanhas:
                    camp['usuarios'] = [u for u in todos_usuarios if u['cliente_id'] == camp['id']]
                    
        except Exception as e:
            print(f"[DB-ERROR] Erro ao carregar Dashboard Master: {e}")
            flash('Erro ao carregar os dados do sistema.', 'danger')
        finally:
            conn.close()

    # Permissões irrestritas para o SuperAdmin
    permissoes_master = {"permite_mapa": True, "permite_equipe": True, "permite_bi": True}
        
    return render_template('superadmin/dashboard.html', campanhas=campanhas, permissoes=permissoes_master)


# ==========================================
# BLOCO 3: GESTÃO DE TENANTS (CAMPANHAS)
# ==========================================

@superadmin_bp.route('/campanhas/nova', methods=['POST'])
def criar_campanha_completa():
    """Provisiona uma nova Campanha e dispara o e-mail de onboarding para o Candidato."""
    if not is_superadmin(): 
        return redirect(url_for('auth.login'))
    
    nome_completo = request.form.get('nome_completo', '').strip()
    email_candidato = request.form.get('email_candidato', '').strip().lower()
    cargo = request.form.get('cargo', '').strip()
    
    campanha_id = f"camp_{uuid.uuid4().hex[:10]}"
    usuario_id = f"usr_{uuid.uuid4().hex[:10]}"
    
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Cria a Campanha (Tenant)
            cursor.execute("""
                INSERT INTO clientes (id, nome_candidato, cargo_disputado, status) 
                VALUES (%s, %s, %s, 'ativo')
            """, (campanha_id, nome_completo, cargo))
            
            # 2. Cria o Candidato (Flag primeiro_acesso = TRUE garantida)
            cursor.execute("""
                INSERT INTO usuarios (id, cliente_id, nome, email, senha_hash, role, primeiro_acesso)
                VALUES (%s, %s, %s, %s, %s, 'candidato', TRUE)
            """, (usuario_id, campanha_id, nome_completo, email_candidato, senha_hash))
            
        conn.commit()
        
        # 3. Disparo Assíncrono do E-mail de Boas-vindas
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
        
        flash('Campanha criada e e-mail de boas-vindas enviado ao candidato.', 'success')
        return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))
        
    except Exception as e:
        conn.rollback()
        print(f"[DB-ERROR] Erro ao criar campanha: {str(e)}")
        flash('Erro ao provisionar o ambiente do cliente.', 'danger')
        return redirect(url_for('superadmin.painel_geral'))
    finally:
        conn.close()

@superadmin_bp.route('/campanhas/<campanha_id>')
def perfil_campanha(campanha_id):
    if not is_superadmin(): 
        return redirect(url_for('auth.login'))
    
    dados = CRMService.get_detalhes_campanha_completa(campanha_id)
    if not dados:
        flash('Campanha não encontrada.', 'danger')
        return redirect(url_for('superadmin.painel_geral'))
        
    return render_template('superadmin/perfil_campanha.html', 
                           campanha=dados['campanha'], 
                           candidato=dados['candidato'], 
                           assessores=dados['assessores'])


# ==========================================
# BLOCO 4: GESTÃO MESTRE DE USUÁRIOS
# ==========================================

@superadmin_bp.route('/campanhas/<campanha_id>/usuario/salvar', methods=['POST'])
def salvar_usuario_campanha(campanha_id):
    """Cria ou edita um usuário (Assessor ou Candidato) dentro de um Tenant."""
    if not is_superadmin(): 
        return redirect(url_for('auth.login'))
    
    usuario_id = request.form.get('usuario_id')
    role = request.form.get('role', 'assessor')
    nome = request.form.get('nome', '').strip()
    email = request.form.get('email', '').strip().lower()
    
    # Roteia para o serviço de atualização de Candidato/Campanha
    if role == 'candidato':
        sucesso = CRMService.salvar_dados_mestre_campanha(campanha_id, request.form)
        if sucesso: flash('Dados mestre da campanha atualizados.', 'success')
        else: flash('Erro ao atualizar dados da campanha.', 'danger')
        return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

    # Lógica Transacional para Assessores (Equipe)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not usuario_id: # NOVO ASSESSOR
                uid = f"usr_{uuid.uuid4().hex[:10]}"
                senha_provisoria = "mudar@votahub"
                senha_hash = generate_password_hash(senha_provisoria)
                
                cursor.execute("""
                    INSERT INTO usuarios (id, cliente_id, nome, email, role, senha_hash, primeiro_acesso)
                    VALUES (%s, %s, %s, %s, 'assessor', %s, TRUE)
                """, (uid, campanha_id, nome, email, senha_hash))
                
                # Disparo de e-mail de Boas-vindas para o Assessor
                corpo_email = f"""
                <div style="font-family: Inter, Arial, sans-serif; color: #1f2937;">
                    <h2 style="color: #4f46e5;">Você foi adicionado à equipe!</h2>
                    <p>Olá, <strong>{nome}</strong>. Um administrador concedeu a você acesso ao VotaHub.</p>
                    <div style="background-color: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                        <p style="margin: 0;"><strong>E-mail:</strong> {email}</p>
                        <p style="margin: 5px 0 0 0;"><strong>Senha Provisória:</strong> <span style="color: #e63946;">{senha_provisoria}</span></p>
                    </div>
                </div>
                """
                disparar_email_assincrono(email, "Convite para Equipe VotaHub", corpo_email)
                flash('Assessor adicionado e e-mail convite disparado.', 'success')
                
            else: # EDIÇÃO DE ASSESSOR
                cursor.execute("""
                    UPDATE usuarios SET nome=%s, email=%s, cpf=%s, sexo=%s, idade=%s, telefone=%s
                    WHERE id=%s AND cliente_id=%s
                """, (nome, email, request.form.get('cpf'), request.form.get('sexo'), 
                      request.form.get('idade') or None, request.form.get('telefone'),
                      usuario_id, campanha_id))
                flash('Dados do assessor atualizados.', 'success')
                
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB-ERROR] Erro ao salvar usuário: {e}")
        flash('Erro interno ao salvar dados do usuário.', 'danger')
    finally:
        conn.close()
        
    return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

@superadmin_bp.route('/usuarios/<usuario_id>/reset-senha', methods=['POST'])
def resetar_senha_usuario(usuario_id):
    """Força o reset de senha para o padrão do sistema."""
    if not is_superadmin(): 
        return redirect(url_for('auth.login'))
    
    campanha_id = request.form.get('campanha_id')
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE usuarios 
                SET senha_hash = %s, primeiro_acesso = TRUE 
                WHERE id = %s RETURNING email, nome
            """, (senha_hash, usuario_id))
            usuario = cursor.fetchone()
            
        if usuario:
            conn.commit()
            
            # Avisa o usuário do reset
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
        conn.close()
        
    return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

@superadmin_bp.route('/usuarios/<usuario_id>/excluir', methods=['POST'])
def excluir_usuario(usuario_id):
    """Revoga o acesso excluindo permanentemente o usuário."""
    if not is_superadmin(): 
        return redirect(url_for('auth.login'))
        
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