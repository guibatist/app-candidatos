import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    try:
        # Puxa a URL completa do .env
        conn_string = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(conn_string)
        return conn
    except Exception as e:
        print(f"❌ Erro Crítico: Falha ao conectar no Neon PostgreSQL: {e}")
        return None