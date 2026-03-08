# === BLOCO 1: DEPENDÊNCIAS E SETUP ===
import os
import uuid
import time
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from psycopg2.extras import RealDictCursor
from app.utils.db import get_db_connection

superadmin_bp = Blueprint('superadmin', __name__)


# === BLOCO 2: HELPERS DE AUTENTICAÇÃO ===
def is_superadmin():
    """
    Verifica se o usuário logado tem privilégios de SuperAdmin.
    TODO: Remover o bypass (return True) quando o controle de sessão estiver 100% testado.
    """
    # Exemplo de implementação real (descomente e ajuste conforme necessário no futuro):
    # return session.get('role') == 'superadmin'
    return True 


# === BLOCO 3: DASHBOARD DO MASTER ===
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
                # Busca todas as campanhas (clientes/tenants)
                cursor.execute("SELECT * FROM clientes ORDER BY created_at DESC")
                campanhas = cursor.fetchall()
                
                # Busca todos os usuários do sistema
                cursor.execute("SELECT id, cliente_id, nome, email, role FROM usuarios")
                todos_usuarios = cursor.fetchall()
                
                # Relaciona os usuários às suas respectivas campanhas em memória (otimização de banco)
                for camp in campanhas:
                    camp['usuarios'] = [u for u in todos_usuarios if u['cliente_id'] == camp['id']]
        except Exception as e:
            print(f"Erro ao carregar Dashboard Master: {e}")
            flash('Erro ao carregar os dados do sistema.', 'danger')
        finally:
            conn.close()

    # Mock de permissões para o SuperAdmin navegar no sistema
    permissoes_mock = {
        "permite_mapa": True,
        "permite_equipe": True,
        "permite_bi": True
    }
        
    return render_template('superadmin/dashboard.html', 
                           campanhas=campanhas, 
                           permissoes=permissoes_mock)


# === BLOCO 4: GESTÃO DE CLIENTES (CAMPANHAS) ===
@superadmin_bp.route('/campanhas/nova', methods=['POST'])
def criar_campanha():
    """Cria um novo Tenant (Cliente) e seu usuário primário (Candidato/Admin da Campanha)."""
    if not is_superadmin():
        return redirect(url_for('auth.login'))
    
    nome_candidato = request.form.get('nome_candidato')
    email_candidato = request.form.get('email_candidato')
    
    # Geração de IDs únicos com prefixos semânticos
    campanha_id = f"camp_{uuid.uuid4().hex[:10]}"
    usuario_id = f"usr_{uuid.uuid4().hex[:10]}"
    senha_hash = generate_password_hash("Mudar@123")
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                # 1. Cria a estrutura da Campanha
                cursor.execute("""
                    INSERT INTO clientes (id, nome_candidato, status) 
                    VALUES (%s, %s, 'ativo')
                """, (campanha_id, nome_candidato))
                
                # 2. Cria a credencial de acesso principal
                cursor.execute("""
                    INSERT INTO usuarios (id, cliente_id, nome, email, senha_hash, role, primeiro_acesso)
                    VALUES (%s, %s, %s, %s, %s, 'candidato', TRUE)
                """, (usuario_id, campanha_id, nome_candidato, email_candidato, senha_hash))
                
            conn.commit()
            flash('Nova campanha configurada com sucesso. A senha temporária do candidato é: Mudar@123', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Erro SQL ao criar campanha: {e}")
            flash('Erro crítico ao provisionar o ambiente do cliente no banco de dados.', 'danger')
        finally:
            conn.close()
    
    return redirect(url_for('superadmin.painel_geral'))


# === BLOCO 5: GESTÃO DE USUÁRIOS (MEMBROS DA CAMPANHA) ===
@superadmin_bp.route('/campanhas/<campanha_id>/assessores', methods=['POST'])
def adicionar_assessor(campanha_id):
    """Adiciona um membro subordinado à uma campanha específica."""
    if not is_superadmin():
        return redirect(url_for('auth.login'))
    
    nome = request.form.get('nome')
    email = request.form.get('email')
    
    usuario_id = f"usr_{uuid.uuid4().hex[:10]}"
    senha_hash = generate_password_hash("Acesso@123")
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO usuarios (id, cliente_id, nome, email, senha_hash, role, primeiro_acesso)
                    VALUES (%s, %s, %s, %s, %s, 'assessor', TRUE)
                """, (usuario_id, str(campanha_id), nome, email, senha_hash))
            conn.commit()
            flash(f'Membro "{nome}" provisionado com sucesso. Senha temporária: Acesso@123', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Erro SQL ao adicionar usuário: {e}")
            flash('Não foi possível registrar o usuário no banco de dados.', 'danger')
        finally:
            conn.close()
    
    return redirect(url_for('superadmin.painel_geral'))

@superadmin_bp.route('/usuarios/<usuario_id>/excluir', methods=['POST'])
def excluir_usuario(usuario_id):
    """Revoga o acesso de um usuário, excluindo-o do sistema."""
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
            print(f"Erro SQL ao excluir usuário: {e}")
            flash('Falha ao tentar remover as credenciais do usuário.', 'danger')
        finally:
            conn.close()
    
    return redirect(url_for('superadmin.painel_geral'))