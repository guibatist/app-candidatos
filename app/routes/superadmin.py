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

# A IMPORTAÇÃO QUE ESTAVA FALTANDO:
from app.utils.mailer import Mailer

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
    Quando um e-mail é alterado, reseta a conta e dispara o convite 
    com o novo template profissional via Mailer.
    """
    from app.utils.mailer import Mailer # Importação necessária
    
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Reseta a senha para o padrão e reativa a trava de primeiro acesso
            cursor.execute("""
                UPDATE usuarios 
                SET senha_hash = %s, primeiro_acesso = TRUE, email = %s
                WHERE id = %s
            """, (senha_hash, novo_email, usuario_id))
        conn.commit()
        
        # DISPARO VIA MAILER
        # Usamos o template de 're_onboarding' para diferenciar de uma conta nova
        try:
            Mailer.enviar_primeiro_acesso(novo_email, nome, senha_provisoria)
            return True
        except Exception as e:
            print(f"🚨 [MAIL-ERROR] Erro no disparo do Re-Onboarding: {e}")
            return True # Retorna True pois o banco foi atualizado
            
    except Exception as e:
        if conn: conn.rollback()
        print(f"🚨 [DB-ERROR] Erro no Re-Onboarding: {e}")
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
    # 1. Captura e Sanitização dos Dados
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
    
    # 2. Geração de Identificadores e Segurança
    campanha_id = f"camp_{uuid.uuid4().hex[:10]}"
    usuario_id = f"usr_{uuid.uuid4().hex[:10]}"
    api_token = secrets.token_hex(16)
    
    # Senha padrão do sistema conforme solicitado
    senha_provisoria = "mudar@votahub"
    senha_hash = generate_password_hash(senha_provisoria)
    
    # 3. Persistência no Banco de Dados
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Inserção do Cliente/Campanha
            cursor.execute("""
                INSERT INTO clientes (id, nome_candidato, cargo_disputado, partido_sigla, partido_numero, status, api_token) 
                VALUES (%s, %s, %s, %s, %s, 'ativo', %s)
            """, (campanha_id, nome_completo, cargo, partido_sigla, partido_numero, api_token))
            
            # Inserção do Usuário (Candidato)
            cursor.execute("""
                INSERT INTO usuarios (id, cliente_id, nome, email, senha_hash, role, primeiro_acesso, cpf, telefone, sexo, idade)
                VALUES (%s, %s, %s, %s, %s, 'candidato', TRUE, %s, %s, %s, %s)
            """, (usuario_id, campanha_id, nome_completo, email_candidato, senha_hash, cpf, telefone, sexo, idade_final))
            
        conn.commit()
        
        # 4. Disparo do E-mail via Mailer (Centralizado)
        try:
            # Usa o template emails/primeiro_acesso.html com o protocolo único
            Mailer.enviar_primeiro_acesso(email_candidato, nome_completo, senha_provisoria)
            flash('Campanha configurada e e-mail enviado com sucesso!', 'success')
        except Exception as mail_err:
            print(f"🚨 [MAIL-ERROR] Falha ao enviar boas-vindas: {mail_err}")
            flash('Campanha criada, mas houve uma falha no envio do e-mail.', 'warning')
            
        return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))
        
    except Exception as e:
        if conn: conn.rollback()
        # Tratamento de erro específico para CPF duplicado
        if 'usuarios_cpf_key' in str(e):
            flash('Este CPF já está cadastrado em outra conta.', 'danger')
        else:
            flash('Erro ao provisionar a base de dados do cliente.', 'danger')
        print(f"🚨 [DB-CRITICAL] Erro ao criar campanha: {e}") 
        return redirect(url_for('superadmin.painel_geral'))
    finally:
        if conn: conn.close()

@superadmin_bp.route('/campanhas/<campanha_id>/usuario/salvar', methods=['POST'])
@login_required
def salvar_usuario_campanha(campanha_id):
    usuario_id = request.form.get('usuario_id')
    role = request.form.get('role', 'assessor')
    nome = request.form.get('nome', '').strip()
    novo_email = request.form.get('email', '').strip().lower()
    
    # Tratamento de tipos (NULL em vez de string vazia)
    cpf = request.form.get('cpf', '').strip() or None
    telefone = request.form.get('telefone', '').strip() or None
    sexo = request.form.get('sexo', '').strip() or None
    idade_raw = request.form.get('idade', '').strip()
    idade_final = int(idade_raw) if idade_raw.isdigit() else None
    
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # ==========================================================
            # 1. VALIDAÇÃO DE UNICIDADE DE E-MAIL (A TRAVA)
            # ==========================================================
            if usuario_id:
                # Se for EDIÇÃO: verifica se o e-mail já existe em OUTRO ID
                cursor.execute("SELECT id FROM usuarios WHERE email = %s AND id != %s", (novo_email, usuario_id))
            else:
                # Se for CRIAÇÃO: verifica se o e-mail já existe no banco todo
                cursor.execute("SELECT id FROM usuarios WHERE email = %s", (novo_email,))
            
            usuario_existente = cursor.fetchone()
            
            if usuario_existente:
                flash(f'O e-mail "{novo_email}" já está sendo usado por outra pessoa no sistema.', 'danger')
                return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

            # ==========================================================
            # 2. BUSCA E-MAIL ANTIGO PARA RE-ONBOARDING
            # ==========================================================
            email_antigo = None
            if usuario_id:
                cursor.execute("SELECT email FROM usuarios WHERE id = %s", (usuario_id,))
                user_db = cursor.fetchone()
                if user_db: email_antigo = user_db['email']

            # --- FLUXO CANDIDATO ---
            if role == 'candidato':
                sucesso = CRMService.salvar_dados_mestre_campanha(campanha_id, request.form)
                if sucesso: 
                    flash('Dados mestre atualizados.', 'success')
                    if email_antigo and email_antigo != novo_email:
                        _executar_re_onboarding(usuario_id, novo_email, nome)
                return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

            # --- FLUXO ASSESSOR ---
            if not usuario_id:
                # INSERT
                uid = f"usr_{uuid.uuid4().hex[:10]}"
                senha_provisoria = "mudar@votahub"
                senha_hash = generate_password_hash(senha_provisoria)
                
                cursor.execute("""
                    INSERT INTO usuarios (id, cliente_id, nome, email, role, senha_hash, primeiro_acesso, cpf, telefone, sexo, idade)
                    VALUES (%s, %s, %s, %s, 'assessor', %s, TRUE, %s, %s, %s, %s)
                """, (uid, campanha_id, nome, novo_email, senha_hash, cpf, telefone, sexo, idade_final))
                
                from app.utils.mailer import Mailer
                Mailer.enviar_primeiro_acesso(novo_email, nome, senha_provisoria)
                flash('Assessor adicionado com sucesso!', 'success')
            else:
                # UPDATE
                cursor.execute("""
                    UPDATE usuarios 
                    SET nome=%s, email=%s, cpf=%s, sexo=%s, idade=%s, telefone=%s
                    WHERE id=%s AND cliente_id=%s
                """, (nome, novo_email, cpf, sexo, idade_final, telefone, usuario_id, campanha_id))
                
                if email_antigo and email_antigo != novo_email:
                    _executar_re_onboarding(usuario_id, novo_email, nome)
                    flash('E-mail alterado. Novas credenciais enviadas.', 'info')
                else:
                    flash('Dados atualizados.', 'success')
                    
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"[DB-ERROR] {e}")
        flash('Erro ao salvar: Verifique se os dados são válidos.', 'danger')
    finally:
        if conn: conn.close()
        
    return redirect(url_for('superadmin.perfil_campanha', campanha_id=campanha_id))

@superadmin_bp.route('/usuarios/<usuario_id>/reset-senha', methods=['POST'])
@login_required
def resetar_senha_usuario(usuario_id):
    """Força o reset de senha para o padrão do sistema E ENVIA O E-MAIL via Mailer."""
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
            
            # DISPARO DO E-MAIL USANDO A NOVA CLASSE MAILER
            try:
                # Aqui chamamos o Mailer que foi importado no topo
                Mailer.enviar_reset_senha(usuario['email'], usuario['nome'], senha_provisoria)
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