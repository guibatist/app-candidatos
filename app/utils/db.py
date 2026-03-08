import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

def get_db_connection():
    """
    Cria e retorna uma conexão com o banco de dados Votahub.
    Usa o RealDictCursor para que as linhas do banco voltem como dicionários (igual ao JSON).
    """
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            database=os.environ.get('DB_NAME', 'votahub'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', ''),
            port=os.environ.get('DB_PORT', '5432')
        )
        return conn
    except Exception as e:
        print(f"❌ Erro Crítico: Falha ao conectar no Votahub PostgreSQL: {e}")
        return None