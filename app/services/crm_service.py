from ..utils.json_helper import load_data, save_data, filter_by_client, get_next_id, delete_item, update_item
from datetime import datetime

class CRMService:
    @staticmethod
    def get_dashboard_data(cliente_id):
        apoiadores = filter_by_client('apoiadores', cliente_id)
        bairros = {}
        for a in apoiadores:
            bairros[a['bairro']] = bairros.get(a['bairro'], 0) + 1
        return {"total_apoiadores": len(apoiadores), "bairros": bairros}

    @staticmethod
    def listar_apoiadores(cliente_id):
        return filter_by_client('apoiadores', cliente_id)

    @staticmethod
    def get_apoiador(cliente_id, apoiador_id):
        apoiadores = filter_by_client('apoiadores', cliente_id)
        return next((a for a in apoiadores if a['id'] == int(apoiador_id)), None)

    @staticmethod
    def adicionar_apoiador(cliente_id, dados):
        apoiadores = load_data('apoiadores')
        novo_apoiador = {
            "id": get_next_id('apoiadores'),
            "cliente_id": int(cliente_id),
            "nome": dados.get('nome'),
            "telefone": dados.get('telefone'),
            "cep": dados.get('cep'),                   # NOVO
            "logradouro": dados.get('logradouro'),     # NOVO
            "numero": dados.get('numero'),             # NOVO
            "uf": dados.get('uf'),
            "cidade": dados.get('cidade'),
            "bairro": dados.get('bairro'),
            "grau_apoio": dados.get('grau_apoio'),
            "data_cadastro": datetime.now().strftime("%d/%m/%Y")
        }
        apoiadores.append(novo_apoiador)
        save_data('apoiadores', apoiadores)
        return novo_apoiador

    @staticmethod
    def excluir_apoiador(cliente_id, apoiador_id):
        delete_item('apoiadores', apoiador_id, cliente_id)

    # ================= LOGICA DE TAREFAS =================
    @staticmethod
    def listar_tarefas_apoiador(cliente_id, apoiador_id):
        tarefas = filter_by_client('tarefas', cliente_id)
        return [t for t in tarefas if t['apoiador_id'] == int(apoiador_id)]

    @staticmethod
    def adicionar_tarefa(cliente_id, apoiador_id, dados):
        tarefas = load_data('tarefas')
        nova_tarefa = {
            "id": get_next_id('tarefas'),
            "cliente_id": int(cliente_id),
            "apoiador_id": int(apoiador_id),
            "tipo": dados.get('tipo'), # Ligar, Visitar, WhatsApp
            "descricao": dados.get('descricao'),
            "data_limite": dados.get('data_limite'),
            "status": "pendente" # pendente ou concluida
        }
        tarefas.append(nova_tarefa)
        save_data('tarefas', tarefas)

    @staticmethod
    def concluir_tarefa(cliente_id, tarefa_id):
        update_item('tarefas', tarefa_id, cliente_id, {"status": "concluida"})