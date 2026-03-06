import requests

query = "Estrada São Cristóvão, Embu das Artes, SP, Brasil"
url = f"https://nominatim.openstreetmap.org/search?format=json&q={query}&limit=1"
headers = {'User-Agent': 'AppCRM_Teste_Isolado/1.0'}

print(f"Buscando: {query}...")
resposta = requests.get(url, headers=headers)

print(f"Código do Servidor: {resposta.status_code}")
try:
    dados = resposta.json()
    if dados:
        print(f"LAT: {dados[0]['lat']} | LON: {dados[0]['lon']}")
    else:
        print("O satélite não achou a rua (Retornou lista vazia [])")
except Exception as e:
    print(f"Erro ao ler os dados: {e}")