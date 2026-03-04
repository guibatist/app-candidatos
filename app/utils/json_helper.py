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

# NOVAS FUNÇÕES:
def get_next_id(table):
    data = load_data(table)
    if not data: return 1
    return max(item['id'] for item in data) + 1

def delete_item(table, item_id, cliente_id):
    data = load_data(table)
    # Garante que só deleta se pertencer ao cliente correto (Multi-tenant)
    nova_lista = [item for item in data if not (item['id'] == int(item_id) and item['cliente_id'] == int(cliente_id))]
    save_data(table, nova_lista)

def update_item(table, item_id, cliente_id, novos_dados):
    data = load_data(table)
    for item in data:
        if item['id'] == int(item_id) and item['cliente_id'] == int(cliente_id):
            item.update(novos_dados)
            break
    save_data(table, data)