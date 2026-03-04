from ..utils.json_helper import load_data, save_data, filter_by_client, get_next_id, delete_item, update_item
from datetime import datetime

class CRMService:
    @staticmethod
    def get_dashboard_data(cliente_id):
        apoiadores = filter_by_client('apoiadores', cliente_id)
        tarefas = filter_by_client('tarefas', cliente_id)
        
        # 1. Total e Grau de Apoio
        total = len(apoiadores)
        multiplicadores = sum(1 for a in apoiadores if a.get('grau_apoio') == 'forte')
        
        # 2. Bairros (Para gráfico de Rosca)
        bairros = {}
        for a in apoiadores:
            bairro_nome = a.get('bairro', 'Não Informado')
            bairros[bairro_nome] = bairros.get(bairro_nome, 0) + 1
            
        # 3. Ativos Físicos (Muros, Carros, Lideranças - Para gráfico de Barras)
        ativos = {
            "Muros Disponíveis": sum(1 for a in apoiadores if a.get('oferece_muro', False)),
            "Carros P/ Adesivo": sum(1 for a in apoiadores if a.get('oferece_carro', False)),
            "Líderes Comunitários": sum(1 for a in apoiadores if a.get('lideranca', False))
        }

        # 4. Score de Influência (Maiores Indicadores)
        indicacoes = {}
        for a in apoiadores:
            indicador = a.get('indicado_por')
            if indicador and indicador.strip() != "":
                indicacoes[indicador] = indicacoes.get(indicador, 0) + 1
        
        # Ordena o dicionário e pega os top 5
        top_influenciadores = dict(sorted(indicacoes.items(), key=lambda item: item[1], reverse=True)[:5])

        # 5. Timeline de Interações (Últimas 5 tarefas concluídas)
        tarefas_concluidas = sorted([t for t in tarefas if t.get('status') == 'concluida'], key=lambda x: x['id'], reverse=True)[:5]
        
        # Anexa o nome do apoiador na tarefa para exibir na timeline
        for t in tarefas_concluidas:
            ap_nome = next((a['nome'] for a in apoiadores if a['id'] == t['apoiador_id']), 'Desconhecido')
            t['apoiador_nome'] = ap_nome

        return {
            "kpis": {
                "total": total,
                "multiplicadores": multiplicadores,
                "ativos_total": sum(ativos.values())
            },
            "grafico_bairros": bairros,
            "grafico_ativos": ativos,
            "top_influenciadores": top_influenciadores,
            "timeline": tarefas_concluidas
        }

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

    # ================= MAPA =================
    @staticmethod
    def concluir_tarefa(cliente_id, tarefa_id):
        update_item('tarefas', tarefa_id, cliente_id, {"status": "concluida"})
    
    @staticmethod
    def get_dados_mapa(cliente_id):
        apoiadores = filter_by_client('apoiadores', cliente_id)
        
        pontos_exatos = []
        for a in apoiadores:
            # Só envia para o mapa quem tem logradouro e cidade preenchidos
            if a.get('logradouro') and a.get('cidade'):
                pontos_exatos.append({
                    "id": a.get('id'),
                    "nome": a.get('nome'),
                    "endereco": f"{a.get('logradouro')}, {a.get('numero', '')}",
                    "bairro": a.get('bairro'),
                    "cidade": a.get('cidade'),
                    "uf": a.get('uf'),
                    "grau_apoio": a.get('grau_apoio', 'medio')
                })
                
        return pontos_exatos