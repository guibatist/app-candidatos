from ..utils.json_helper import load_data, save_data, filter_by_client, get_next_id, delete_item, update_item
import uuid
from datetime import datetime
import os 
import random
import requests

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
    def get_apoiadores(cliente_id):
        from app.utils.json_helper import load_data
        # Carrega a lista completa de apoiadores do arquivo JSON
        todos_apoiadores = load_data('apoiadores')
        
        # Filtra apenas os que pertencem ao cliente_id (campanha) atual
        # Usamos str() para garantir que a comparação não falhe entre "1" e 1
        return [a for a in todos_apoiadores if str(a.get('cliente_id')) == str(cliente_id)]

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
    def buscar_coordenadas(logradouro, numero, bairro, cidade, uf, cep):
        import requests
        import time
        
        headers = {'User-Agent': 'AppCRM_Eleitoral_SaaS/1.0'}

        tentativas = [
            f"{logradouro}, {numero}, {cidade}, {uf}, Brasil",
            f"{logradouro}, {cidade}, {uf}, Brasil",
            f"{cep}, Brasil",
            f"{bairro}, {cidade}, {uf}, Brasil"
        ]

        for query in tentativas:
            if not query or query.startswith(',') or len(query) < 5:
                continue
                
            try:
                url = f"https://nominatim.openstreetmap.org/search?format=json&q={query}&limit=1"
                time.sleep(1) 
                response = requests.get(url, headers=headers).json()
                
                # A CORREÇÃO ESTÁ AQUI: O OpenStreetMap usa 'lon' e não 'lng'
                if response and isinstance(response, list) and len(response) > 0:
                    lat = float(response[0]['lat'])
                    lng = float(response[0]['lon']) # <--- A letra 'o' salva o dia!
                    
                    print(f"🎯 SUCESSO Geocoding: '{query}' -> {lat}, {lng}")
                    return lat, lng
            except Exception as e:
                print(f"❌ Erro na API para '{query}': {e}")
                
        print(f"⚠️ Geocoding esgotou as tentativas.")
        return None, None

    @staticmethod
    def adicionar_apoiador(cliente_id, dados_form):
        from app.utils.json_helper import load_data, save_data
        import os
        from datetime import datetime
        import time
        
        apoiadores = load_data('apoiadores')
        
        # 1. Captura os dados do formulário com segurança
        nome = dados_form.get('nome', '').strip()
        telefone = dados_form.get('telefone', '').strip()
        cep = dados_form.get('cep', '').strip()
        # Pega logradouro ou rua dependendo do 'name' no seu HTML
        logradouro = dados_form.get('logradouro', dados_form.get('rua', '')).strip()
        numero = dados_form.get('numero', '').strip()
        complemento = dados_form.get('complemento', '').strip()
        bairro = dados_form.get('bairro', '').strip()
        cidade = dados_form.get('cidade', '').strip()
        uf = dados_form.get('uf', '').strip()
        
        # 2. BUSCA INTELIGENTE EM CASCATA (Fallback Semântico)
        # Envia os pedaços separados para a função que criamos acima
        lat, lng = CRMService.buscar_coordenadas(logradouro, numero, bairro, cidade, uf, cep)
        
        # 3. Gera ID único seguro (tenta os.times() primeiro, senão usa time.time())
        try:
            novo_id = str(len(apoiadores) + 1 + int(os.times().elapsed))
        except AttributeError:
            novo_id = str(len(apoiadores) + 1 + int(time.time()))

        # 4. Monta o objeto completo para salvar no JSON
        novo = {
            "id": novo_id,
            "cliente_id": str(cliente_id),
            "nome": nome,
            "telefone": telefone,
            "cep": cep,
            "logradouro": logradouro,
            "numero": numero,
            "complemento": complemento,
            "bairro": bairro,
            "cidade": cidade,
            "uf": uf,
            "lat": lat, # Agora salva a coordenada real (ou null se falhar em todas as tentativas)
            "lng": lng, # Agora salva a coordenada real (ou null se falhar em todas as tentativas)
            "grau_apoio": dados_form.get('grau_apoio', 'medio'),
            "votos_familia": int(dados_form.get('votos_familia', 1) or 1),
            "tags": dados_form.get('tags', '').split(',') if isinstance(dados_form.get('tags'), str) else [],
            "indicado_por": dados_form.get('indicado_por', ''),
            "observacoes": dados_form.get('observacoes', ''),
            "oferece_muro": str(dados_form.get('oferece_muro')).lower() in ['on', 'true', '1'],
            "oferece_carro": str(dados_form.get('oferece_carro')).lower() in ['on', 'true', '1'],
            "lideranca": str(dados_form.get('lideranca')).lower() in ['on', 'true', '1'],
            "data_cadastro": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        
        apoiadores.append(novo)
        save_data('apoiadores', apoiadores)
        return novo

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
    def obter_coordenadas(endereco):
        try:
            # Consulta o OpenStreetMap (Gratuito e sem chave de API inicial)
            url = f"https://nominatim.openstreetmap.org/search?format=json&q={endereco}"
            headers = {'User-Agent': 'CRM-Politico-App'}
            response = requests.get(url, headers=headers).json()
            
            if response:
                return float(response[0]['lat']), float(response[0]['lng'])
        except Exception as e:
            print(f"Erro no Geocoding: {e}")
        return None, None

    @staticmethod
    def get_dados_mapa(cliente_id):
        from app.utils.json_helper import load_data
        apoiadores = load_data('apoiadores')
        
        # Puxa os apoiadores deste cliente
        meus_apoiadores = [a for a in apoiadores if str(a.get('cliente_id')) == str(cliente_id)]
        
        # AGORA ENVIAMOS O APOIADOR INDIVIDUAL (Com nome, rua, etc) PARA NÃO DAR UNDEFINED
        dados_formatados = []
        for a in meus_apoiadores:
            if a.get('lat') and a.get('lng'): # Só envia pro mapa quem tem coordenada válida
                dados_formatados.append({
                    "nome": a.get('nome', 'Apoiador sem nome'),
                    "logradouro": a.get('logradouro', ''),
                    "numero": a.get('numero', ''),
                    "bairro": a.get('bairro', ''),
                    "cidade": a.get('cidade', ''),
                    "grau_apoio": a.get('grau_apoio', 'medio'),
                    "lideranca": a.get('lideranca', False),
                    "lat": a.get('lat'),
                    "lng": a.get('lng')
                })
                
        return dados_formatados

# ================= LOGICA DE EQUIPE =================
    @staticmethod
    def get_equipe_completa(cliente_id):
        from app.utils.json_helper import load_data
        # Carrega todos os usuários e filtra apenas os que pertencem a esta campanha
        usuarios = load_data('usuarios')
        return [u for u in usuarios if str(u.get('cliente_id')) == str(cliente_id)]

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
    
