import json, os

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data')

def load_data(table):
    path = os.path.join(DATA_PATH, f"{table}.json")
    if not os.path.exists(path): return []
    with open(path, 'r', encoding='utf-8') as f: return json.load(f)

def save_data(table, data):
    path = os.path.join(DATA_PATH, f"{table}.json")
    with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

def filter_by_client(table, cliente_id):
    return [item for item in load_data(table) if item.get('cliente_id') == int(cliente_id)]