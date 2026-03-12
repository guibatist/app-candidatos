import smtplib
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Usando os nomes que estão no seu arquivo
host = os.getenv('SMTP_HOST')
port = os.getenv('SMTP_PORT')
user = os.getenv('SMTP_USER')
passw = os.getenv('SMTP_PASS')

print(f"DEBUG: HOST={host}, PORT={port}, USER={user}")

try:
    if not host or not port:
        raise ValueError("Variáveis não encontradas! Verifique se os nomes no .env batem.")

    print("Conectando...")
    server = smtplib.SMTP(host, int(port))
    server.starttls()
    print("Logando...")
    server.login(user, passw)
    print("SUCESSO!")
    server.quit()
except Exception as e:
    print(f"ERRO: {e}")