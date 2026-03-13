from app.utils.db import get_db_connection
from app.utils.mailer import Mailer

class CronService:
    @staticmethod
    def processar_relatorios_semanais():
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, nome_candidato FROM clientes WHERE status = 'ativo'")
                campanhas = cursor.fetchall()
                
                for camp in campanhas:
                    cliente_id = camp[0]
                    nome_candidato = camp[1]
                    
                    cursor.execute("""
                        SELECT t.id, t.tipo, t.data_limite, u.nome as assessor_nome
                        FROM tarefas t
                        LEFT JOIN usuarios u ON t.assessor_id = u.id
                        WHERE t.cliente_id = %s 
                          AND t.status IN ('pendente', 'atrasada') 
                          AND t.data_limite IS NOT NULL 
                          AND t.data_limite != ''
                          AND t.data_limite::DATE < CURRENT_DATE
                        ORDER BY t.data_limite ASC
                    """, (cliente_id,))
                    
                    colunas = [desc[0] for desc in cursor.description]
                    tarefas_atrasadas = [dict(zip(colunas, row)) for row in cursor.fetchall()]
                    
                    if tarefas_atrasadas:
                        cursor.execute("SELECT email FROM usuarios WHERE cliente_id = %s", (cliente_id,))
                        equipe = cursor.fetchall()
                        
                        for membro in equipe:
                            email_membro = membro[0]
                            # LOG PARA VOCÊ VER NO TERMINAL QUEM ENTROU NA FILA
                            print(f"[CRON] Preparando disparo para: {email_membro}")
                            try:
                                Mailer.enviar_relatorio_atrasos(
                                    email_destinatario=email_membro,
                                    nome_candidato=nome_candidato,
                                    tarefas=tarefas_atrasadas
                                )
                            except Exception as e:
                                print(f"[CRON-ERROR] Falha interna no Mailer para {email_membro}: {e}")
            return True
        except Exception as e:
            print(f"[CRON-ERROR] Falha geral no processamento: {e}")
            return False
        finally:
            if conn: conn.close()