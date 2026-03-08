import uuid
import json
import requests
import time
from datetime import datetime
from psycopg2.extras import RealDictCursor
from app.utils.db import get_db_connection

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

class CRMService:
    
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
                # ILIKE faz busca ignorando maiúsculas/minúsculas no Postgres
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
                        indicado_por, observacoes, oferece_muro, oferece_carro, lideranca, data_cadastro
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) RETURNING *
                """, (
                    novo_id, str(cliente_id), nome, telefone, cep, logradouro, numero, complemento,
                    bairro, cidade, uf, lat, lon, dados_form.get('grau_apoio', 'medio'),
                    int(dados_form.get('votos_familia', 1) or 1), json.dumps(tags_list),
                    dados_form.get('indicado_por', ''), dados_form.get('observacoes', ''),
                    oferece_muro, oferece_carro, lideranca, datetime.now().strftime("%d/%m/%Y %H:%M")
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
                cursor.execute("""
                    INSERT INTO tarefas (id, cliente_id, apoiador_id, tipo, descricao, data_limite, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pendente')
                """, (novo_id, str(cliente_id), str(apoiador_id), dados.get('tipo'), dados.get('descricao'), dados.get('data_limite')))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao adicionar tarefa: {e}")
        finally:
            conn.close()

    @staticmethod
    def concluir_tarefa(cliente_id, tarefa_id):
        conn = get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE tarefas SET status = 'concluida' WHERE id = %s AND cliente_id = %s", (str(tarefa_id), str(cliente_id)))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Erro ao concluir tarefa: {e}")
        finally:
            conn.close()

    @staticmethod
    def get_dados_mapa(cliente_id):
        conn = get_db_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # O Frontend espera 'lng', mas o banco salva como 'lon'. Tratamos isso na saída:
                cursor.execute("""
                    SELECT nome, logradouro, numero, bairro, cidade, grau_apoio, lideranca, lat, lon as lng
                    FROM apoiadores 
                    WHERE cliente_id = %s AND lat IS NOT NULL AND lon IS NOT NULL
                """, (str(cliente_id),))
                return cursor.fetchall()
        except Exception as e:
            print(f"Erro ao buscar dados do mapa: {e}")
            return []
        finally:
            conn.close()

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