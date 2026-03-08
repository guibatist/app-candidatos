from werkzeug.security import generate_password_hash
from app.utils.db import get_db_connection
import uuid

def criar_admin():
    conn = get_db_connection()
    if not conn:
        print("Erro de conexão com o banco.")
        return
        
    try:
        with conn.cursor() as cursor:
            # Gera um ID único
            novo_id = f"usr_{uuid.uuid4().hex[:10]}"
            # Criptografa a senha "123456"
            senha_criptografada = generate_password_hash("123456")
            
            cursor.execute("""
                INSERT INTO usuarios (id, nome, email, senha_hash, role, primeiro_acesso)
                VALUES (%s, %s, %s, %s, %s, FALSE)
            """, (novo_id, 'Admin Master', 'admin@votahub.com', senha_criptografada, 'superadmin'))
            
            conn.commit()
            print("✅ Usuário Super Admin criado com sucesso no Votahub!")
            print("Email: admin@votahub.com | Senha: 123456")
    except Exception as e:
        conn.rollback()
        print(f"❌ Erro ao criar admin: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    criar_admin()