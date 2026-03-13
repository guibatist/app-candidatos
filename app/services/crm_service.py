# === BLOCO 1: DEPENDÊNCIAS E SETUP ===
import uuid
import json
import requests
import time
from datetime import datetime
from psycopg2.extras import RealDictCursor
from app.utils.db import get_db_connection
from app.utils.mailer import Mailer
# === BLOCO 2: SERVIÇO CORE DO CRM ===
class CRMService:
    
    # ==========================================
    # SUB-BLOCO 2.1: DASHBOARD E MÉTRICAS (ALTA PERFORMANCE)
    # ==========================================
    @staticmethod
    def get_dashboard_data(cliente_id):
        """
        Dashboard remodelado com agregações no Banco de Dados.
        Inclui as demandas recentes vindas do site do candidato.
        """
        conn = get_db_connection()
        if not conn: 
            return {"kpis": {}, "demandas": [], "grafico_bairros": {}, "grafico_ativos": {}, "top_influenciadores": {}, "timeline": []}
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # 1. KPIs Globais e Ativos
                cursor.execute("""
                    SELECT 
                        COUNT(id) as total,
                        COALESCE(SUM(votos_familia), 0) as potencial_votos,
                        SUM(CASE WHEN grau_apoio = 'forte' THEN 1 ELSE 0 END) as multiplicadores,
                        SUM(CASE WHEN oferece_muro = TRUE THEN 1 ELSE 0 END) as muros,
                        SUM(CASE WHEN oferece_carro = TRUE THEN 1 ELSE 0 END) as carros,
                        SUM(CASE WHEN lideranca = TRUE THEN 1 ELSE 0 END) as lideres
                    FROM apoiadores 
                    WHERE cliente_id = %s
                """, (str(cliente_id),))
                kpis_db = cursor.fetchone()

                # 2. Demandas Recentes do Site (COM OS NOMES CORRETOS DAS COLUNAS DA NEON)
                cursor.execute("""
                    SELECT 
                        id, 
                        nome_solicitante AS nome, 
                        descricao AS mensagem, 
                        data_recebimento AS criado_em, 
                        status 
                    FROM demandas_site 
                    WHERE cliente_id = %s 
                    ORDER BY data_recebimento DESC LIMIT 5
                """, (str(cliente_id),))
                demandas_recentes = cursor.fetchall()

                # 3. Agrupamento de Bairros
                cursor.execute("""
                    SELECT COALESCE(NULLIF(bairro, ''), 'Não Informado') as bairro, COUNT(id) as qtd 
                    FROM apoiadores 
                    WHERE cliente_id = %s 
                    GROUP BY 1 ORDER BY 2 DESC
                """, (str(cliente_id),))
                bairros = {row['bairro']: row['qtd'] for row in cursor.fetchall()}

                # 4. Top Influenciadores
                cursor.execute("""
                    SELECT indicado_por, COUNT(id) as qtd 
                    FROM apoiadores 
                    WHERE cliente_id = %s AND indicado_por IS NOT NULL AND indicado_por != ''
                    GROUP BY 1 ORDER BY 2 DESC LIMIT 5
                """, (str(cliente_id),))
                top_influenciadores = {row['indicado_por']: row['qtd'] for row in cursor.fetchall()}

                # 5. Timeline de Tarefas Concluídas
                cursor.execute("""
                    SELECT t.id, t.descricao, t.data_criacao, t.status, a.nome as apoiador_nome 
                    FROM tarefas t
                    LEFT JOIN apoiadores a ON t.apoiador_id = a.id
                    WHERE t.cliente_id = %s AND t.status IN ('concluida', 'concluído')
                    ORDER BY t.data_criacao DESC LIMIT 5
                """, (str(cliente_id),))
                timeline = cursor.fetchall()

            return {
                "kpis": {
                    "total": kpis_db['total'] or 0,
                    "potencial_votos": kpis_db['potencial_votos'] or 0,
                    "multiplicadores": kpis_db['multiplicadores'] or 0,
                    "ativos_total": (kpis_db['muros'] or 0) + (kpis_db['carros'] or 0) + (kpis_db['lideres'] or 0)
                },
                "demandas": demandas_recentes,
                "grafico_bairros": bairros,
                "grafico_ativos": {"Muros": kpis_db['muros'] or 0, "Carros": kpis_db['carros'] or 0, "Líderes": kpis_db['lideres'] or 0},
                "top_influenciadores": top_influenciadores,
                "timeline": timeline
            }
        except Exception as e:
            print(f"[DB-ERROR] Erro ao gerar dashboard otimizado: {e}")
            return {"kpis": {}, "demandas": [], "grafico_bairros": {}, "grafico_ativos": {}, "top_influenciadores": {}, "timeline": []}
        finally:
            conn.close()

    # No arquivo de Service (onde está o get_dashboard_data ou similar)
    @staticmethod
    def listar_demandas(cliente_id):
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # AQUI ESTÁ A TRAVA: O banco só entrega o que for desse cliente_id
                cursor.execute("""
                    SELECT * FROM demandas_site 
                    WHERE cliente_id = %s 
                    ORDER BY data_recebimento DESC
                """, (cliente_id,))
                return cursor.fetchall()
        finally:
            conn.close()

    # ==========================================
    # SUB-BLOCO 2.2: GEOINTELIGÊNCIA
    # ==========================================
    @staticmethod
    def buscar_coordenadas(logradouro, numero, bairro, cidade, uf, cep):
        headers = {'User-Agent': 'Votahub_SaaS/1.0'}
        tentativas = [
            f"{logradouro}, {numero}, {cidade}, {uf}, Brasil",
            f"{logradouro}, {cidade}, {uf}, Brasil",
            f"{cep}, Brasil",
            f"{bairro}, {cidade}, {uf}, Brasil"
        ]

        for query in tentativas:
            if not query or query.startswith(',') or len(query) < 5: continue
            try:
                url = f"https://nominatim.openstreetmap.org/search?format=json&q={query}&limit=1"
                time.sleep(1) # Respeito ao limite do Nominatim (1 req/sec)
                response = requests.get(url, headers=headers, timeout=5).json()
                if response and isinstance(response, list) and len(response) > 0:
                    lat = float(response[0]['lat'])
                    lon = float(response[0]['lon'])
                    print(f"[GEO] SUCESSO Geocoding: '{query}' -> {lat}, {lon}")
                    return lat, lon
            except Exception as e:
                print(f"[GEO-ERROR] Falha na API para '{query}': {e}")
                
        print(f"[GEO-WARN] Geocoding esgotou as tentativas. Sem coordenadas.")
        return None, None

    @staticmethod
    def get_dados_mapa(cliente_id):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT nome, logradouro, numero, bairro, cidade, grau_apoio, lideranca, lat, lon as lng
                    FROM apoiadores 
                    WHERE cliente_id = %s AND lat IS NOT NULL AND lon IS NOT NULL
                """, (str(cliente_id),))
                return cursor.fetchall()
        finally:
            conn.close()


    # ==========================================
    # SUB-BLOCO 2.3: GESTÃO DE APOIADORES (CRUD)
    # ==========================================
    @staticmethod
    def get_apoiadores(cliente_id):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM apoiadores WHERE cliente_id = %s ORDER BY data_cadastro DESC", (str(cliente_id),))
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def buscar_apoiadores_por_nome(cliente_id, termo):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, nome FROM apoiadores 
                    WHERE cliente_id = %s AND nome ILIKE %s 
                    LIMIT 10
                """, (str(cliente_id), f"%{termo}%"))
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def adicionar_apoiador(cliente_id, dados_form):
        nome = dados_form.get('nome', '').strip()
        telefone = dados_form.get('telefone', '').strip()
        cep = dados_form.get('cep', '').strip()
        logradouro = dados_form.get('logradouro', dados_form.get('rua', '')).strip()
        numero = dados_form.get('numero', '').strip()
        complemento = dados_form.get('complemento', '').strip()
        bairro = dados_form.get('bairro', '').strip()
        cidade = dados_form.get('cidade', '').strip()
        uf = dados_form.get('uf', '').strip()
        
        lat, lon = CRMService.buscar_coordenadas(logradouro, numero, bairro, cidade, uf, cep)
        novo_id = f"apo_{uuid.uuid4().hex[:12]}"
        
        tags = dados_form.get('tags', '')
        tags_list = tags.split(',') if isinstance(tags, str) and tags else []

        oferece_muro = str(dados_form.get('oferece_muro')).lower() in ['on', 'true', '1']
        oferece_carro = str(dados_form.get('oferece_carro')).lower() in ['on', 'true', '1']
        lideranca = str(dados_form.get('lideranca')).lower() in ['on', 'true', '1']

        conn = get_db_connection()
        if not conn: return None
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO apoiadores (
                        id, cliente_id, nome, telefone, cep, logradouro, numero, complemento, 
                        bairro, cidade, uf, lat, lon, grau_apoio, votos_familia, tags, 
                        indicado_por, observacoes, oferece_muro, oferece_carro, lideranca, data_cadastro,
                        sexo, faixa_etaria, renda_familiar, grau_instrucao, origem_cadastro, posicionamento_politico
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    ) RETURNING *
                """, (
                    novo_id, str(cliente_id), nome, telefone, cep, logradouro, numero, complemento,
                    bairro, cidade, uf, lat, lon, dados_form.get('grau_apoio', 'medio'),
                    int(dados_form.get('votos_familia', 1) or 1), json.dumps(tags_list),
                    dados_form.get('indicado_por', ''), dados_form.get('observacoes', ''),
                    oferece_muro, oferece_carro, lideranca, datetime.now(),
                    dados_form.get('sexo') or None,
                    dados_form.get('faixa_etaria') or None,
                    dados_form.get('renda_familiar') or None,
                    dados_form.get('grau_instrucao') or None,
                    dados_form.get('origem_cadastro') or None,
                    dados_form.get('posicionamento_politico') or None
                ))
                novo_apoiador = cursor.fetchone()
            conn.commit()
            return novo_apoiador
        except Exception as e:
            conn.rollback()
            print(f"[DB-ERROR] Erro ao salvar apoiador: {e}")
            return None
        finally:
            conn.close()

    @staticmethod
    def atualizar_perfil_demografico(cliente_id, apoiador_id, dados):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE apoiadores 
                    SET sexo = %s, faixa_etaria = %s, renda_familiar = %s,
                        grau_instrucao = %s, origem_cadastro = %s, posicionamento_politico = %s
                    WHERE id = %s AND cliente_id = %s
                """, (
                    dados.get('sexo') or None, dados.get('faixa_etaria') or None,
                    dados.get('renda_familiar') or None, dados.get('grau_instrucao') or None,
                    dados.get('origem_cadastro') or None, dados.get('posicionamento_politico') or None,
                    str(apoiador_id), str(cliente_id)
                ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[DB-ERROR] Erro ao atualizar demografia: {e}")
        finally:
            conn.close()

    @staticmethod
    def atualizar_cadastro_geral(cliente_id, apoiador_id, dados_form):
        cep = dados_form.get('cep', '').strip()
        logradouro = dados_form.get('logradouro', '').strip()
        numero = dados_form.get('numero', '').strip()
        bairro = dados_form.get('bairro', '').strip()
        cidade = dados_form.get('cidade', '').strip()
        uf = dados_form.get('uf', '').strip()
        
        lat, lon = CRMService.buscar_coordenadas(logradouro, numero, bairro, cidade, uf, cep)

        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE apoiadores 
                    SET nome = %s, telefone = %s, cep = %s, logradouro = %s, numero = %s,
                        complemento = %s, bairro = %s, cidade = %s, uf = %s,
                        lat = COALESCE(%s, lat), lon = COALESCE(%s, lon), 
                        grau_apoio = %s, votos_familia = %s,
                        oferece_muro = %s, oferece_carro = %s, lideranca = %s
                    WHERE id = %s AND cliente_id = %s
                """, (
                    dados_form.get('nome', '').strip(), dados_form.get('telefone', '').strip(), 
                    cep, logradouro, numero, dados_form.get('complemento', '').strip(), 
                    bairro, cidade, uf, lat, lon, 
                    dados_form.get('grau_apoio', 'medio'), int(dados_form.get('votos_familia', 1) or 1),
                    str(dados_form.get('oferece_muro')).lower() in ['on', 'true', '1'], 
                    str(dados_form.get('oferece_carro')).lower() in ['on', 'true', '1'], 
                    str(dados_form.get('lideranca')).lower() in ['on', 'true', '1'],
                    str(apoiador_id), str(cliente_id)
                ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[DB-ERROR] Erro ao atualizar cadastro: {e}")
        finally:
            conn.close()

    @staticmethod
    def excluir_apoiador(cliente_id, apoiador_id):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM apoiadores WHERE id = %s AND cliente_id = %s", (str(apoiador_id), str(cliente_id)))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            conn.close()


    # ==========================================
    # SUB-BLOCO 2.4: GESTÃO DE TAREFAS
    # ==========================================
    @staticmethod
    def adicionar_tarefa(cliente_id, apoiador_id, dados, criador_id=None):
        """
        Cria a tarefa e gera o alerta inicial para o executor com o link de redirecionamento.
        """
        from app.routes.auth import enviar_alerta_sistema 
        from datetime import datetime
        import uuid

        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # 1. Gera o ID da Tarefa
                nova_tarefa_id = f"tar_{uuid.uuid4().hex[:12]}"
                assessor_id = dados.get('assessor_id')
                assessor_id = None if not assessor_id or assessor_id.strip() in ['', 'None'] else assessor_id
                
                # 2. Insere a Tarefa no Banco
                cursor.execute("""
                    INSERT INTO tarefas (id, cliente_id, apoiador_id, assessor_id, criador_id, tipo, descricao, data_limite, status, data_criacao)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pendente', %s)
                """, (nova_tarefa_id, str(cliente_id), str(apoiador_id), assessor_id, criador_id, 
                      dados.get('tipo'), dados.get('descricao'), dados.get('data_limite') or None, datetime.now()))

                # 3. Adiciona o Criador como Membro (Transparência)
                if criador_id and assessor_id and str(criador_id) != str(assessor_id):
                    cursor.execute("""
                        INSERT INTO tarefa_membros (tarefa_id, usuario_id, papel) 
                        VALUES (%s, %s, 'membro') ON CONFLICT DO NOTHING
                    """, (nova_tarefa_id, str(criador_id)))

                # 4. GERA A NOTIFICAÇÃO COM O LINK (REF) PARA O EXECUTOR
                if assessor_id:
                    id_aviso = str(uuid.uuid4())
                    # AQUI ESTÁ O LINK: [Ref:nova_tarefa_id]
                    msg_aviso = f"Você recebeu uma nova missão: '{dados.get('tipo')}'. [Ref:{nova_tarefa_id}]"
                    
                    cursor.execute("""
                        INSERT INTO tarefas (id, cliente_id, assessor_id, tipo, descricao, status, lida)
                        VALUES (%s, %s, %s, 'Aviso de Sistema', %s, 'pendente', FALSE)
                    """, (id_aviso, str(cliente_id), assessor_id, msg_aviso))

                conn.commit()
                print(f"[CRM] Tarefa {nova_tarefa_id} criada com sucesso.")

        except Exception as e:
            if conn: conn.rollback()
            print(f"[DB-ERROR] Erro ao criar tarefa: {e}")
            raise e
        finally:
            if conn: conn.close()

    @staticmethod
    def alterar_status_tarefa(cliente_id, tarefa_id, novo_status):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE tarefas SET status = %s WHERE id = %s AND cliente_id = %s", 
                               (novo_status, str(tarefa_id), str(cliente_id)))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            conn.close()

    @staticmethod
    def excluir_tarefa(cliente_id, tarefa_id):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM tarefas WHERE id = %s AND cliente_id = %s", (str(tarefa_id), str(cliente_id)))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            conn.close()


    # ==========================================
    # SUB-BLOCO 2.5: GESTÃO DE EQUIPE E TENANT (SaaS)
    # ==========================================
    @staticmethod
    def listar_equipe(cliente_id):
        """Lista os usuários da campanha, filtrando Masters do sistema."""
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, nome, email, role, data_criacao as data_cadastro 
                    FROM usuarios 
                    WHERE cliente_id = %s AND role NOT IN ('superadmin', 'admin', 'master')
                    ORDER BY role ASC, nome ASC
                """, (str(cliente_id),))
                return cursor.fetchall()
        except Exception as e:
            print(f"[DB-ERROR] Erro ao listar equipe: {e}")
            return []
        finally:
            conn.close()

    @staticmethod
    def get_detalhes_campanha_completa(campanha_id):
        conn = get_db_connection()
        if not conn: return None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Busca a campanha
                cursor.execute("SELECT * FROM clientes WHERE id = %s", (campanha_id,))
                campanha = cursor.fetchone()
                
                # Busca o candidato (Dono da campanha) com TODOS os campos
                cursor.execute("""
                    SELECT id, nome, email, role, cpf, telefone, sexo, idade 
                    FROM usuarios 
                    WHERE cliente_id = %s AND role = 'candidato'
                """, (campanha_id,))
                candidato = cursor.fetchone()
                
                # Busca a equipe (assessores)
                cursor.execute("SELECT * FROM usuarios WHERE cliente_id = %s AND role = 'assessor'", (campanha_id,))
                assessores = cursor.fetchall()
                
                return {
                    'campanha': campanha,
                    'candidato': candidato,
                    'assessores': assessores
                }
        finally:
            conn.close()

    @staticmethod
    def salvar_dados_mestre_campanha(campanha_id, dados):
        """Atualização Atômica: Tabela Clientes (SaaS) + Tabela Usuarios (Candidato)."""
        conn = get_db_connection()
        if not conn: return False
            
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE clientes SET 
                        partido_sigla = %s, partido_numero = %s, cargo_disputado = %s
                    WHERE id = %s
                """, (
                    dados.get('partido_sigla', '').upper(), dados.get('partido_numero'),
                    dados.get('cargo'), campanha_id
                ))

                cursor.execute("""
                    UPDATE usuarios SET 
                        nome = %s, email = %s, cpf = %s, sexo = %s, idade = %s, telefone = %s
                    WHERE cliente_id = %s AND role = 'candidato'
                """, (
                    dados.get('nome'), dados.get('email'), dados.get('cpf'),
                    dados.get('sexo'), dados.get('idade'), dados.get('telefone'),
                    campanha_id
                ))
            conn.commit()
            return True
        except Exception as e:
            if conn: conn.rollback()
            print(f"[DB-CRITICAL] Erro ao salvar dados mestre: {e}")
            return False
        finally:
            if conn: conn.close()