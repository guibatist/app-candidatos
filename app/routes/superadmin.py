import os
import uuid
import time
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from psycopg2.extras import RealDictCursor
from app.utils.db import get_db_connection

superadmin_bp = Blueprint('superadmin', __name__)

def is_superadmin():
    # Mantendo seu bypass temporário para facilitar o acesso
    return True

# ==========================================
# ROTAS DO PAINEL MASTER (POSTGRES)
# ==========================================

@superadmin_bp.route('/dashboard')
def painel_geral():
    if not is_superadmin():
        flash('Acesso negado.', 'danger')
        return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    campanhas = []
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Busca todas as campanhas (clientes)
                cursor.execute("SELECT * FROM clientes ORDER BY created_at DESC")
                campanhas = cursor.fetchall()
                
                # Busca todos os usuários
                cursor.execute("SELECT id, cliente_id, nome, email, role FROM usuarios")
                todos_usuarios = cursor.fetchall()
                
                # Vincula usuários às campanhas na memória para o template
                for camp in campanhas:
                    camp['usuarios'] = [u for u in todos_usuarios if u['cliente_id'] == camp['id']]
        finally:
            conn.close()

    permissoes_mock = {
        "permite_mapa": True,
        "permite_equipe": True,
        "permite_bi": True
    }
        
    return render_template('superadmin/dashboard.html', 
                           campanhas=campanhas, 
                           permissoes=permissoes_mock)

@superadmin_bp.route('/campanhas/nova', methods=['POST'])
def criar_campanha():
    if not is_superadmin():
        return redirect(url_for('auth.login'))
    
    nome_candidato = request.form.get('nome_candidato')
    email_candidato = request.form.get('email_candidato')
    
    # Geramos IDs únicos profissionais
    campanha_id = f"camp_{uuid.uuid4().hex[:10]}"
    usuario_id = f"usr_{uuid.uuid4().hex[:10]}"
    senha_hash = generate_password_hash("Mudar@123")
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                # 1. Cria o Cliente (Candidato)
                cursor.execute("""
                    INSERT INTO clientes (id, nome_candidato, status) 
                    VALUES (%s, %s, 'ativo')
                """, (campanha_id, nome_candidato))
                
                # 2. Cria o Usuário Master do Candidato
                cursor.execute("""
                    INSERT INTO usuarios (id, cliente_id, nome, email, senha_hash, role, primeiro_acesso)
                    VALUES (%s, %s, %s, %s, %s, 'candidato', TRUE)
                """, (usuario_id, campanha_id, nome_candidato, email_candidato, senha_hash))
                
            conn.commit()
            flash('Campanha e Usuário criados no Postgres! Senha: Mudar@123', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar no banco: {e}', 'danger')
        finally:
            conn.close()
    
    return redirect(url_for('superadmin.painel_geral'))

@superadmin_bp.route('/campanhas/<campanha_id>/assessores', methods=['POST'])
def adicionar_assessor(campanha_id):
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
            flash(f'Assessor {nome} adicionado! Senha: Acesso@123', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao adicionar assessor: {e}', 'danger')
        finally:
            conn.close()
    
    return redirect(url_for('superadmin.painel_geral'))

@superadmin_bp.route('/usuarios/<usuario_id>/excluir', methods=['POST'])
def excluir_usuario(usuario_id):
    if not is_superadmin():
        return redirect(url_for('auth.login'))
        
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM usuarios WHERE id = %s", (str(usuario_id),))
            conn.commit()
            flash('Acesso revogado com sucesso no banco.', 'warning')
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao excluir: {e}', 'danger')
        finally:
            conn.close()
    
    return redirect(url_for('superadmin.painel_geral'))