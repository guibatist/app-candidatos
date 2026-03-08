# === BLOCO 1: DEPENDÊNCIAS E SETUP ===
import uuid
import json
import requests
import time
from datetime import datetime
from psycopg2.extras import RealDictCursor
from app.utils.db import get_db_connection


# === BLOCO 2: FUNÇÕES HELPERS GLOBAIS ===
# (Funções auxiliares que operam fora da classe principal)

def listar_tarefas_por_usuario(cliente_id, usuario_id, role, apoiador_id):
    conn = get_db_connection()
    if not conn: return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if role == 'assessor':
                cursor.execute("""
                    SELECT * FROM tarefas 
                    WHERE cliente_id = %s AND apoiador_id = %s AND assessor_id = %s
                """, (str(cliente_id), str(apoiador_id), str(usuario_id)))
            else:
                cursor.execute("""
                    SELECT * FROM tarefas 
                    WHERE cliente_id = %s AND apoiador_id = %s
                """, (str(cliente_id), str(apoiador_id)))
            return cursor.fetchall()
    except Exception as e:
        print(f"Erro ao listar tarefas do usuario: {e}")
        return []
    finally:
        conn.close()

def criar_tarefa(cliente_id, apoiador_id, descricao, assessor_id=None):
    nova_tarefa = {
        "id": f"tar_{uuid.uuid4().hex[:12]}",
        "cliente_id": str(cliente_id),
        "apoiador_id": str(apoiador_id),
        "assessor_id": str(assessor_id) if assessor_id else None,
        "descricao": descricao,
        "status": "pendente",
        "data_criacao": datetime.now().isoformat()
    }
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO tarefas (id, cliente_id, apoiador_id, assessor_id, descricao, status, data_criacao)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (nova_tarefa['id'], nova_tarefa['cliente_id'], nova_tarefa['apoiador_id'], 
                      nova_tarefa['assessor_id'], nova_tarefa['descricao'], nova_tarefa['status'], nova_tarefa['data_criacao']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao criar tarefa: {e}")
        finally:
            conn.close()
            
    return nova_tarefa


# === BLOCO 3: SERVIÇO CORE DO CRM ===
class CRMService:
    
    # --- SUB-BLOCO 3.1: DASHBOARD E MÉTRICAS ---
    @staticmethod
    def get_dashboard_data(cliente_id):
        conn = get_db_connection()
        if not conn: return {"kpis": {}, "grafico_bairros": {}, "grafico_ativos": {}, "top_influenciadores": {}, "timeline": []}
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM apoiadores WHERE cliente_id = %s", (str(cliente_id),))
                apoiadores = cursor.fetchall()
                
                cursor.execute("SELECT * FROM tarefas WHERE cliente_id = %s", (str(cliente_id),))
                tarefas = cursor.fetchall()
                
            total = len(apoiadores)
            potencial_votos = sum(int(a.get('votos_familia') or 1) for a in apoiadores)
            multiplicadores = sum(1 for a in apoiadores if a.get('grau_apoio') == 'forte')
            
            bairros = {}
            ativos = {"Muros": 0, "Carros": 0, "Líderes": 0}
            indicacoes = {}
            
            for a in apoiadores:
                # Agrupamento de Bairros
                bairro_nome = a.get('bairro') or 'Não Informado'
                bairros[bairro_nome] = bairros.get(bairro_nome, 0) + 1
                
                # Agrupamento de Ativos
                if a.get('oferece_muro'): ativos["Muros"] += 1
                if a.get('oferece_carro'): ativos["Carros"] += 1
                if a.get('lideranca'): ativos["Líderes"] += 1
                
                # Influenciadores
                indicador = a.get('indicado_por')
                if indicador and indicador.strip():
                    indicacoes[indicador] = indicacoes.get(indicador, 0) + 1
                    
            top_influenciadores = dict(sorted(indicacoes.items(), key=lambda item: item[1], reverse=True)[:5])

            tarefas_concluidas = sorted([t for t in tarefas if t.get('status') == 'concluida'], key=lambda x: str(x.get('data_criacao', '')), reverse=True)[:5]
            for t in tarefas_concluidas:
                ap_nome = next((a['nome'] for a in apoiadores if a['id'] == t['apoiador_id']), 'Desconhecido')
                t['apoiador_nome'] = ap_nome

            return {
                "kpis": {
                    "total": total,
                    "potencial_votos": potencial_votos,
                    "multiplicadores": multiplicadores,
                    "ativos_total": sum(ativos.values())
                },
                "grafico_bairros": bairros,
                "grafico_ativos": ativos,
                "top_influenciadores": top_influenciadores,
                "timeline": tarefas_concluidas
            }
        except Exception as e:
            print(f"Erro ao gerar dashboard: {e}")
            return {}
        finally:
            conn.close()


    # --- SUB-BLOCO 3.2: GEOINTELIGÊNCIA (MAPAS E NOMINATIM) ---
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
                time.sleep(1) 
                response = requests.get(url, headers=headers).json()
                if response and isinstance(response, list) and len(response) > 0:
                    lat = float(response[0]['lat'])
                    lon = float(response[0]['lon'])
                    print(f"🎯 SUCESSO Geocoding: '{query}' -> {lat}, {lon}")
                    return lat, lon
            except Exception as e:
                print(f"❌ Erro na API para '{query}': {e}")
                
        print(f"⚠️ Geocoding esgotou as tentativas.")
        return None, None

    @staticmethod
    def get_dados_mapa(cliente_id):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Importante: 'lon as lng' faz a tradução para o JavaScript entender
                cursor.execute("""
                    SELECT nome, logradouro, numero, bairro, cidade, grau_apoio, lideranca, lat, lon as lng
                    FROM apoiadores 
                    WHERE cliente_id = %s AND lat IS NOT NULL AND lon IS NOT NULL
                """, (str(cliente_id),))
                return cursor.fetchall()
        except Exception as e:
            print(f"❌ Erro SQL no Mapa: {e}")
            return []
        finally:
            conn.close()


    # --- SUB-BLOCO 3.3: GESTÃO DE APOIADORES (CRUD) ---
    @staticmethod
    def listar_apoiadores(cliente_id):
        return CRMService.get_apoiadores(cliente_id)

    @staticmethod
    def get_apoiadores(cliente_id):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM apoiadores WHERE cliente_id = %s ORDER BY created_at DESC", (str(cliente_id),))
                return cursor.fetchall()
        except Exception as e:
            print(f"Erro ao buscar apoiadores: {e}")
            return []
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
        except Exception as e:
            print(f"Erro na busca por nome: {e}")
            return []
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
        
        # Faz a mágica do Mapa (Geocoding)
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
                    oferece_muro, oferece_carro, lideranca, datetime.now().strftime("%d/%m/%Y %H:%M"),
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
            print(f"Erro ao salvar apoiador no banco: {e}")
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
            print(f"Erro ao atualizar perfil demográfico: {e}")
        finally:
            conn.close()

    @staticmethod
    def atualizar_cadastro_geral(cliente_id, apoiador_id, dados_form):
        nome = dados_form.get('nome', '').strip()
        telefone = dados_form.get('telefone', '').strip()
        cep = dados_form.get('cep', '').strip()
        logradouro = dados_form.get('logradouro', '').strip()
        numero = dados_form.get('numero', '').strip()
        complemento = dados_form.get('complemento', '').strip()
        bairro = dados_form.get('bairro', '').strip()
        cidade = dados_form.get('cidade', '').strip()
        uf = dados_form.get('uf', '').strip()
        grau_apoio = dados_form.get('grau_apoio', 'medio')
        votos_familia = int(dados_form.get('votos_familia', 1) or 1)

        oferece_muro = str(dados_form.get('oferece_muro')).lower() in ['on', 'true', '1']
        oferece_carro = str(dados_form.get('oferece_carro')).lower() in ['on', 'true', '1']
        lideranca = str(dados_form.get('lideranca')).lower() in ['on', 'true', '1']

        lat, lon = CRMService.buscar_coordenadas(logradouro, numero, bairro, cidade, uf, cep)

        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE apoiadores 
                    SET nome = %s, telefone = %s, cep = %s, logradouro = %s, numero = %s,
                        complemento = %s, bairro = %s, cidade = %s, uf = %s,
                        lat = %s, lon = %s, grau_apoio = %s, votos_familia = %s,
                        oferece_muro = %s, oferece_carro = %s, lideranca = %s
                    WHERE id = %s AND cliente_id = %s
                """, (
                    nome, telefone, cep, logradouro, numero, complemento, bairro, cidade, uf,
                    lat, lon, grau_apoio, votos_familia, oferece_muro, oferece_carro, lideranca,
                    str(apoiador_id), str(cliente_id)
                ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao atualizar cadastro geral: {e}")
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
            print(f"Erro ao excluir apoiador: {e}")
        finally:
            conn.close()


    # --- SUB-BLOCO 3.4: GESTÃO DE TAREFAS ---
    @staticmethod
    def listar_tarefas_apoiador(cliente_id, apoiador_id):
        return listar_tarefas_por_usuario(cliente_id, None, 'admin', apoiador_id)

    @staticmethod
    def adicionar_tarefa(cliente_id, apoiador_id, dados):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                novo_id = f"tar_{uuid.uuid4().hex[:12]}"
                assessor_id = dados.get('assessor_id')
                if not assessor_id or assessor_id.strip() == '':
                    assessor_id = None
                    
                cursor.execute("""
                    INSERT INTO tarefas (id, cliente_id, apoiador_id, assessor_id, tipo, descricao, data_limite, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendente')
                """, (novo_id, str(cliente_id), str(apoiador_id), assessor_id, 
                      dados.get('tipo'), dados.get('descricao'), dados.get('data_limite')))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao adicionar tarefa: {e}")
        finally:
            conn.close()

    @staticmethod
    def alterar_status_tarefa(cliente_id, tarefa_id, novo_status):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE tarefas SET status = %s 
                    WHERE id = %s AND cliente_id = %s
                """, (novo_status, str(tarefa_id), str(cliente_id)))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao alterar status: {e}")
        finally:
            conn.close()

    @staticmethod
    def editar_tarefa(cliente_id, tarefa_id, dados):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE tarefas 
                    SET tipo = %s, descricao = %s, data_limite = %s, status = COALESCE(%s, status)
                    WHERE id = %s AND cliente_id = %s
                """, (dados.get('tipo'), dados.get('descricao'), dados.get('data_limite'), 
                      dados.get('status'), str(tarefa_id), str(cliente_id)))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao editar tarefa: {e}")
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
            print(f"Erro ao excluir tarefa: {e}")
        finally:
            conn.close()


    # --- SUB-BLOCO 3.5: GESTÃO DE EQUIPE ---
    @staticmethod
    def get_equipe_completa(cliente_id):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM equipe WHERE cliente_id = %s", (str(cliente_id),))
                return cursor.fetchall()
        except Exception as e:
            print(f"Erro ao buscar equipe: {e}")
            return []
        finally:
            conn.close()

    @staticmethod
    def adicionar_membro_equipe(cliente_id, dados):
        conn = get_db_connection()
        if not conn: return None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                novo_id = f"eqp_{uuid.uuid4().hex[:12]}"
                cursor.execute("""
                    INSERT INTO equipe (id, cliente_id, nome, telefone, cargo, meta_apoiadores, data_cadastro)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *
                """, (novo_id, str(cliente_id), dados.get('nome'), dados.get('telefone'), 
                      dados.get('cargo'), int(dados.get('meta_apoiadores') or 0), datetime.now().strftime("%d/%m/%Y")))
                novo_membro = cursor.fetchone()
            conn.commit()
            return novo_membro
        except Exception as e:
            conn.rollback()
            print(f"Erro ao adicionar membro na equipe: {e}")
            return None
        finally:
            conn.close()

    @staticmethod
    def excluir_membro_equipe(cliente_id, membro_id):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM equipe WHERE id = %s AND cliente_id = %s", (str(membro_id), str(cliente_id)))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao excluir equipe: {e}")
        finally:
            conn.close()

    @staticmethod
    def get_progresso_equipe(cliente_id):
        equipe = CRMService.get_equipe_completa(cliente_id)
        apoiadores = CRMService.get_apoiadores(cliente_id)
        
        resultados = []
        for membro in equipe:
            captados = sum(1 for a in apoiadores if a.get('indicado_por') == membro['nome'])
            meta = membro.get('meta_apoiadores', 1)
            if meta == 0: meta = 1
            percentual = min(int((captados / meta) * 100), 100)
            
            resultados.append({
                "membro": membro,
                "captados": captados,
                "percentual": percentual
            })
        return resultados
    
    @staticmethod
    def listar_equipe(cliente_id):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor() as cursor:
                # Mudamos de 'papel' para 'role'
                cursor.execute("""
                    SELECT id, nome, email, role, created_at 
                    FROM usuarios 
                    WHERE cliente_id = %s AND role != 'master'
                    ORDER BY nome ASC
                """, (str(cliente_id),))
                
                colunas = [desc[0] for desc in cursor.description]
                return [dict(zip(colunas, row)) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Erro ao listar equipe: {e}")
            return []
        finally:
            conn.close()

# === BLOCO: GESTÃO DE EQUIPE (MÉTODOS ADICIONADOS) ===

    @staticmethod
    def listar_equipe(cliente_id):
        """
        Lista todos os usuários vinculados a uma campanha específica,
        exceto usuários com nível de acesso Master/SaaS.
        """
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Mudamos de 'papel' para 'role' para manter consistência com auth.py
                cursor.execute("""
                    SELECT id, nome, email, role, data_cadastro 
                    FROM usuarios 
                    WHERE cliente_id = %s AND role NOT IN ('superadmin', 'admin', 'master')
                    ORDER BY nome ASC
                """, (str(cliente_id),))
                return cursor.fetchall()
        except Exception as e:
            print(f"Erro ao listar equipe no service: {e}")
            return []
        finally:
            conn.close()

    @staticmethod
    def buscar_apoiadores_por_nome(cliente_id, termo):
        """Busca rápida para componentes de AutoComplete ou BI."""
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

# === BLOCO: ATUALIZAÇÃO MESTRE DE CAMPANHA (SUPERADMIN) ===
    @staticmethod
    def atualizar_campanha_completa(campanha_id, dados):
        conn = get_db_connection()
        if not conn: return False
        try:
            with conn.cursor() as cursor:
                # 1. Atualiza a Campanha (Tabela Clientes)
                cursor.execute("""
                    UPDATE clientes SET 
                        nome_candidato = %s, partido_sigla = %s, partido_numero = %s,
                        cargo_disputado = %s, territorio_estado = %s, territorio_cidade = %s
                    WHERE id = %s
                """, (
                    dados.get('nome_completo'), dados.get('partido_sigla'), 
                    dados.get('partido_numero'), dados.get('cargo'), 
                    dados.get('estado'), dados.get('cidade'), campanha_id
                ))

                # 2. Atualiza o Candidato (Tabela Usuarios)
                # Filtramos pelo cliente_id e pelo role 'candidato'
                cursor.execute("""
                    UPDATE usuarios SET 
                        nome = %s, email = %s, cpf = %s, sexo = %s, 
                        idade = %s, telefone = %s
                    WHERE cliente_id = %s AND role = 'candidato'
                """, (
                    dados.get('nome_completo'), dados.get('email_candidato'),
                    dados.get('cpf_candidato'), dados.get('sexo_candidato'),
                    dados.get('idade_candidato'), dados.get('tel_candidato'),
                    campanha_id
                ))
                
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Erro Crítico na Atualização: {e}")
            return False
        finally:
            conn.close()

# === BLOCO: GESTÃO DE TENANT (CAMPANHA COMPLETA) ===
    @staticmethod
    def get_detalhes_campanha_completa(campanha_id):
        conn = get_db_connection()
        if not conn: return None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # 1. Busca Dados da Campanha
                cursor.execute("SELECT * FROM clientes WHERE id = %s", (campanha_id,))
                campanha = cursor.fetchone()
                
                if not campanha: return None

                # 2. Busca Todos os Usuários vinculados (Candidato e Assessores)
                cursor.execute("""
                    SELECT id, nome, email, cpf, sexo, idade, telefone, role, data_criacao 
                    FROM usuarios 
                    WHERE cliente_id = %s 
                    ORDER BY role ASC, nome ASC
                """, (campanha_id,))
                usuarios = cursor.fetchall()
                
                return {
                    "campanha": campanha,
                    "candidato": next((u for u in usuarios if u['role'] == 'candidato'), None),
                    "assessores": [u for u in usuarios if u['role'] == 'assessor']
                }
        finally:
            conn.close()

# === BLOCO: ATUALIZAÇÃO UNIFICADA (CANDIDATO + PARTIDO) ===
    @staticmethod
    def salvar_dados_mestre_campanha(campanha_id, dados):
        """
        Atualiza simultaneamente a tabela de Clientes (Partido/Cargo) 
        e a tabela de Usuários (Dados do Candidato).
        """
        conn = get_db_connection()
        if not conn: 
            return False
            
        try:
            with conn.cursor() as cursor:
                # 1. Atualiza a Tabela de Clientes (Partido e Cargo)
                # Note a indentação: 8 espaços para dentro da classe/método
                cursor.execute("""
                    UPDATE clientes SET 
                        partido_sigla = %s, 
                        partido_numero = %s, 
                        cargo_disputado = %s
                    WHERE id = %s
                """, (
                    dados.get('partido_sigla', '').upper(),
                    dados.get('partido_numero'),
                    dados.get('cargo'),  # Certifique-se que o <select> no HTML chama-se 'cargo'
                    campanha_id
                ))

                # 2. Atualiza a Tabela de Usuários (Dados Pessoais do Candidato)
                cursor.execute("""
                    UPDATE usuarios SET 
                        nome = %s, 
                        email = %s, 
                        cpf = %s, 
                        sexo = %s, 
                        idade = %s, 
                        telefone = %s
                    WHERE cliente_id = %s AND role = 'candidato'
                """, (
                    dados.get('nome'), 
                    dados.get('email'), 
                    dados.get('cpf'),
                    dados.get('sexo'), 
                    dados.get('idade'), 
                    dados.get('telefone'),
                    campanha_id
                ))
                
            # Confirma a transação atômica (ou muda tudo ou não muda nada)
            conn.commit()
            return True
            
        except Exception as e:
            if conn:
                conn.rollback()
            print(f"❌ Erro ao salvar dados mestre: {e}")
            return False
            
        finally:
            if conn:
                conn.close()