from ..utils.json_helper import load_data, save_data, filter_by_client, get_next_id, delete_item, update_item
import uuid
from datetime import datetime

def listar_tarefas_por_usuario(cliente_id, usuario_id, role, apoiador_id):
    from app.utils.json_helper import load_data
    todas = load_data('tarefas.json') 
    
    # Filtro Robusto: converte tudo para string para evitar erro de tipo (Int vs Str)
    tarefas = [t for t in todas if str(t.get('cliente_id')) == str(cliente_id) 
               and str(t.get('apoiador_id')) == str(apoiador_id)]
    
    # Regra de Equipe: Se for assessor, filtra apenas as dele [cite: 80, 126]
    if role == 'assessor':
        tarefas = [t for t in tarefas if str(t.get('assessor_id')) == str(usuario_id)]
        
    return tarefas

def criar_tarefa(cliente_id, apoiador_id, descricao, assessor_id=None):
    """
    Cria uma nova tarefa. O assessor_id agora pode ser passado (delegação).
    """
    tarefas = load_data('tarefas.json')
    nova_tarefa = {
        "id": str(uuid.uuid4()),
        "cliente_id": str(cliente_id),
        "apoiador_id": str(apoiador_id),
        "assessor_id": str(assessor_id) if assessor_id else None,
        "descricao": descricao,
        "status": "Pendente",
        "data_criacao": datetime.now().isoformat()
    }
    
    tarefas.append(nova_tarefa)
    save_data('tarefas.json', tarefas)
    return nova_tarefa

class CRMService:
    @staticmethod
    def get_dashboard_data(cliente_id):
        apoiadores = filter_by_client('apoiadores', cliente_id)
        tarefas = filter_by_client('tarefas', cliente_id)
        
        # 1. Total, Potencial de Votos e Grau de Apoio
        total = len(apoiadores)
        # Calcula a soma de votos na família (se não tiver o campo, conta como 1)
        potencial_votos = sum(int(a.get('votos_familia', 1)) for a in apoiadores)
        multiplicadores = sum(1 for a in apoiadores if a.get('grau_apoio') == 'forte')
        
        bairros = {}
        for a in apoiadores:
            bairro_nome = a.get('bairro', 'Não Informado')
            bairros[bairro_nome] = bairros.get(bairro_nome, 0) + 1
            
        ativos = {
            "Muros": sum(1 for a in apoiadores if a.get('oferece_muro', False)),
            "Carros": sum(1 for a in apoiadores if a.get('oferece_carro', False)),
            "Líderes": sum(1 for a in apoiadores if a.get('lideranca', False))
        }

        indicacoes = {}
        for a in apoiadores:
            indicador = a.get('indicado_por')
            if indicador and indicador.strip() != "":
                indicacoes[indicador] = indicacoes.get(indicador, 0) + 1
        top_influenciadores = dict(sorted(indicacoes.items(), key=lambda item: item[1], reverse=True)[:5])

        tarefas_concluidas = sorted([t for t in tarefas if t.get('status') == 'concluida'], key=lambda x: x['id'], reverse=True)[:5]
        for t in tarefas_concluidas:
            ap_nome = next((a['nome'] for a in apoiadores if a['id'] == t['apoiador_id']), 'Desconhecido')
            t['apoiador_nome'] = ap_nome

        return {
            "kpis": {
                "total": total,
                "potencial_votos": potencial_votos, # NOVO
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
    def buscar_apoiadores_por_nome(cliente_id, termo):
        apoiadores = filter_by_client('apoiadores', cliente_id)
        termo = termo.lower()
        
        # Filtra apoiadores cujo nome contenha o termo digitado (como o LIKE %% do SQL)
        resultados = []
        for a in apoiadores:
            if termo in a.get('nome', '').lower():
                resultados.append({
                    "id": a['id'],
                    "nome": a['nome']
                })
                
        # Retorna apenas os 10 primeiros para não travar a tela
        return resultados[:10]

    @staticmethod
    def adicionar_apoiador(cliente_id, dados):
        apoiadores = load_data('apoiadores')
        novo_apoiador = {
            "id": get_next_id('apoiadores'),
            "cliente_id": int(cliente_id),
            "nome": dados.get('nome'),
            "telefone": dados.get('telefone'),
            "cep": dados.get('cep'),
            "logradouro": dados.get('logradouro'),
            "numero": dados.get('numero'),
            "complemento": dados.get('complemento', ''),
            "uf": dados.get('uf'),
            "cidade": dados.get('cidade'),
            "bairro": dados.get('bairro'),
            
            "grau_apoio": dados.get('grau_apoio'),
            "votos_familia": int(dados.get('votos_familia', 1)), # NOVO
            "tags": dados.getlist('tags') if hasattr(dados, 'getlist') else [], # NOVO (Lista de interesses)
            
            "indicado_por": dados.get('indicado_por', ''),
            "observacoes": dados.get('observacoes', ''),
            
            "oferece_muro": 'oferece_muro' in dados,
            "oferece_carro": 'oferece_carro' in dados,
            "lideranca": 'lideranca' in dados,
            
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

# ================= LOGICA DE EQUIPE =================
    @staticmethod
    def listar_equipe(cliente_id):
        return filter_by_client('equipe', cliente_id)

    @staticmethod
    def adicionar_membro_equipe(cliente_id, dados):
        equipe = load_data('equipe')
        novo_membro = {
            "id": get_next_id('equipe'),
            "cliente_id": int(cliente_id),
            "nome": dados.get('nome'),
            "telefone": dados.get('telefone'),
            "cargo": dados.get('cargo'), # Coordenador, Assessor, Voluntário
            "meta_apoiadores": int(dados.get('meta_apoiadores', 0)),
            "data_cadastro": datetime.now().strftime("%d/%m/%Y")
        }
        equipe.append(novo_membro)
        save_data('equipe', equipe)
        return novo_membro

    @staticmethod
    def excluir_membro_equipe(cliente_id, membro_id):
        delete_item('equipe', membro_id, cliente_id)

    @staticmethod
    def get_progresso_equipe(cliente_id):
        """Calcula quantos apoiadores cada membro já trouxe em relação à meta"""
        equipe = filter_by_client('equipe', cliente_id)
        apoiadores = filter_by_client('apoiadores', cliente_id)
        
        resultados = []
        for membro in equipe:
            # Conta quantos apoiadores têm este membro como "indicado_por" (match exato de nome por enquanto)
            # No futuro, o ideal é salvar o ID do membro no apoiador
            captados = sum(1 for a in apoiadores if a.get('indicado_por') == membro['nome'])
            
            meta = membro.get('meta_apoiadores', 1)
            if meta == 0: meta = 1 # Evita divisão por zero
            
            percentual = int((captados / meta) * 100)
            if percentual > 100: percentual = 100
            
            resultados.append({
                "membro": membro,
                "captados": captados,
                "percentual": percentual
            })
            
        return resultados
    
