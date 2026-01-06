# ==========================================================
# API BACKEND - AGIL SAAS (Versão Postgres + Webhook ON)
# ==========================================================
import os
import shutil
import json
import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
import psycopg2
import psycopg2.extras 
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import base64
import mercadopago
from datetime import datetime, date, timedelta

# Configure com SEU token
sdk_mp = mercadopago.SDK("APP_USR-6043577431380897-010214-6fda7216b75311bb6ead096cc799021d-83186555")

# --- CONFIGURAÇÃO DE PASTAS ---
os.makedirs("uploads", exist_ok=True)
os.environ["PYTHONIOENCODING"] = "utf-8"

app = FastAPI()

# Monta a pasta para ser acessível via URL 
app.mount("/arquivos", StaticFiles(directory="uploads"), name="arquivos")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- VARIÁVEL DE MEMÓRIA (QUEM ESTÁ ONDE) ---
# Formato: {'556499998888': ID_DO_MENU_ATUAL_INTEIRO}
user_state = {}

# --- CONFIGURAÇÕES ---
EVO_API_URL = "http://127.0.0.1:8080" # Evolution Local
EVO_API_KEY = "159632"                # Sua Key
DOMAIN_URL = "https://api.modestotech.com.br"


# Configurações do Banco (PostgreSQL)
DB_USER = "postgres"
DB_PASS = "3adefe283b724adebd02930fd4b1386c"
DB_HOST = "127.0.0.1"
DB_NAME = "evolution"
DB_PORT = "5432"

def get_connection():
    try:
        dsn = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS} connect_timeout=10"
        conn = psycopg2.connect(dsn)
        conn.set_client_encoding('UTF8')
        return conn
    except Exception as e:
        print(f"ERRO NA CONEXÃO: {str(e)}")
        raise e

# --- MODELOS ---
class Gatilho(BaseModel):
    instancia: str
    gatilho: str
    resposta: str
    titulo_menu: Optional[str] = "Geral"
    categoria: Optional[str] = "Atendimento"
    tipo_midia: Optional[str] = "texto"
    url_midia: Optional[str] = None
    id_pai: Optional[int] = None 

class ConsultaGatilho(BaseModel):
    instancia: str
    mensagem: str
    numero: str 

# ==============================================================================
# FUNÇÃO DE ENVIO V3 (CORRIGIDA: FILTRO POR INSTÂNCIA PARA NÃO MISTURAR CLIENTES)
# ==============================================================================
def enviar_mensagem_smart(instancia, numero, texto, id_gatilho_atual=None, apenas_texto=False):
    print(f"📤 Enviando para {numero}...")
    
    tem_sub_menus = False
    opcoes = []
    
    # SÓ busca opções se NÃO for 'apenas_texto'
    if not apenas_texto:
        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            if id_gatilho_atual:
                # Busca filhos (Sub-menus)
                cur.execute("SELECT gatilho, titulo_menu FROM respostas_automacao WHERE id_pai = %s AND instancia = %s", (id_gatilho_atual, instancia))
            else:
                # Busca Menu Principal (Raiz)
                cur.execute("SELECT gatilho, titulo_menu FROM respostas_automacao WHERE instancia = %s AND id_pai IS NULL AND gatilho != 'default'", (instancia,))
                
            opcoes = cur.fetchall()
            conn.close()
            
            if opcoes:
                tem_sub_menus = True
        except Exception as e:
            print(f"Erro ao buscar menu: {e}")

    # Monta Payload
    payload = {"number": numero, "text": texto}
    
    # Anexa o menu se tiver
    if tem_sub_menus:
        payload["text"] += "\n\n👇 *Opções:*"
        for op in opcoes:
            mostrar = op.get('titulo_menu') or op['gatilho']
            payload["text"] += f"\n*{op['gatilho']}* - {mostrar}"

    # Envia
    try:
        requests.post(
            f"{EVO_API_URL}/message/sendText/{instancia}", 
            json=payload, 
            headers={"apikey": EVO_API_KEY}, 
            timeout=10
        )
        
        # Log
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO chat_logs (instancia, remote_jid, from_me, tipo) VALUES (%s, %s, TRUE, 'texto')", (instancia, numero))
            conn.commit()
            conn.close()
        except: pass
        
    except Exception as e:
        print(f"Erro envio: {e}")

# --- TABELA DE PREÇOS OFICIAL (Backend é a autoridade) ---
PRECOS_OFICIAIS = {
    "Básico": 9.90,
    "Pro": 29.90,
    "Enterprise": 49.90
}

@app.post("/publico/registrar")
async def registrar_publico(dados: dict):
    print(f"💰 Novo registro: {dados['nome']} | Plano: {dados['plano']}")
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # 1. Verifica duplicidade
        cur.execute("SELECT id FROM usuarios WHERE login = %s OR instancia_wa = %s", (dados['login'], dados['instancia']))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Login ou Instância já existem.")

        # 2. CALCULA O VALOR REAL (Segurança)
        valor_base = PRECOS_OFICIAIS.get(dados['plano'], 99.90)
        valor_final = valor_base
        cupom_aplicado = None

        # 3. VERIFICA CUPOM
        if dados.get('cupom'):
            cupom_codigo = dados['cupom'].upper().strip()
            cur.execute("SELECT desconto_porcentagem FROM cupons WHERE codigo = %s AND ativo = TRUE", (cupom_codigo,))
            res_cupom = cur.fetchone()
            
            if res_cupom:
                desconto = res_cupom[0]
                desconto_reais = (valor_base * desconto) / 100
                valor_final = valor_base - desconto_reais
                cupom_aplicado = f"{cupom_codigo} ({desconto}%)"
                print(f"🎟️ Cupom {cupom_codigo} aplicado! De {valor_base} por {valor_final}")
            else:
                print(f"⚠️ Cupom inválido: {cupom_codigo}")

        # Garante 2 casas decimais
        valor_final = round(valor_final, 2)

        # --- NOVO: TRATAMENTO PARA CUPOM DE 100% (GRÁTIS) ---
        if valor_final <= 0:
            print("🎁 Cupom de 100% detectado! Liberando acesso direto...")
            
            # Insere já como ATIVO e com 30 dias de validade
            cur.execute("""
                INSERT INTO usuarios (nome_cliente, login, senha, instancia_wa, plano, valor_mensal, email, whatsapp, status_conta, data_vencimento, id_pagamento_mp) 
                VALUES (%s, %s, %s, %s, %s, 0.00, %s, %s, 'ativo', CURRENT_DATE + INTERVAL '30 days', 'CUPOM_100_OFF')
            """, (
                dados['nome'], dados['login'], dados['senha'], dados['instancia'], 
                dados['plano'], dados['email'], dados['whatsapp']
            ))
            conn.commit()
            
            # Opcional: Aqui você poderia já chamar a criação da instância na Evolution se quisesse
            
            conn.close()
            return {"status": "ativado_direto", "valor_final": 0.00}
        # ----------------------------------------------------

        # 4. Gera o Pagamento no Mercado Pago
        payment_data = {
            "transaction_amount": valor_final,
            "description": f"Assinatura {dados['plano']} - {dados['nome']} {f'- Cupom {cupom_aplicado}' if cupom_aplicado else ''}",
            "payment_method_id": "pix",
            "payer": {
                "email": dados['email'],
                "first_name": dados['nome']
            },
            "notification_url": f"{DOMAIN_URL}/webhook/pagamento"
        }
        
        print(f"📡 Enviando para Mercado Pago (R$ {valor_final})...")
        payment_response = sdk_mp.payment().create(payment_data)
        pagamento = payment_response.get("response", {})
        status_mp = payment_response.get("status")
        
        # --- BLOCO DE DEBUG DETALHADO ---
        if status_mp not in [200, 201]:
            print("❌ O MERCADO PAGO RECUSOU!")
            print(f"🔍 Motivo: {pagamento}")
            
            msg_erro = pagamento.get('message', 'Erro desconhecido no Mercado Pago')
            if 'cause' in pagamento and len(pagamento['cause']) > 0:
                msg_erro = pagamento['cause'][0].get('description', msg_erro)

            raise HTTPException(status_code=400, detail=f"Falha no Pagamento: {msg_erro}")
        # --------------------------------

        id_mp = str(pagamento['id'])
        qr_code = pagamento['point_of_interaction']['transaction_data']['qr_code']
        qr_code_base64 = pagamento['point_of_interaction']['transaction_data']['qr_code_base64']

        # 5. Salva no Banco como PENDENTE
        cur.execute("""
            INSERT INTO usuarios (nome_cliente, login, senha, instancia_wa, plano, valor_mensal, email, whatsapp, status_conta, id_pagamento_mp) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pendente', %s)
        """, (
            dados['nome'], dados['login'], dados['senha'], dados['instancia'], 
            dados['plano'], valor_final, dados['email'], dados['whatsapp'], id_mp
        ))
        conn.commit()
        conn.close()
        
        return {
            "status": "aguardando_pagamento",
            "qr_code": qr_code,
            "qr_base64": qr_code_base64,
            "valor_final": valor_final
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook/pagamento")
async def webhook_pagamento(request: Request):
    try:
        # O MP manda variações, as vezes vem no query, as vezes no body
        params = request.query_params
        topic = params.get("topic") or params.get("type")
        id_obj = params.get("id") or params.get("data.id")

        if topic == "payment":
            print(f"🔔 Notificação de Pagamento ID: {id_obj}")

            # Consulta status atual no MP
            payment_info = sdk_mp.payment().get(id_obj)
            status = payment_info["response"]["status"]

            if status == "approved":
                conn = get_connection()
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

                # Busca o usuário dono desse pagamento
                cur.execute("SELECT * FROM usuarios WHERE id_pagamento_mp = %s", (str(id_obj),))
                user = cur.fetchone()

                if user and user['status_conta'] == 'pendente':
                    print(f"✅ Pagamento Aprovado para {user['nome_cliente']}! Ativando...")

                    # 1. Ativa no Banco
                    cur.execute("UPDATE usuarios SET status_conta = 'ativo' WHERE id = %s", (user['id'],))
                    conn.commit()

                    # 2. Cria Instância na Evolution (Auto-Provisionamento)
                    try:
                        # Cria Instância
                        requests.post(f"{EVO_API_URL}/instance/create", 
                                      json={"instanceName": user['instancia_wa'], "token": user['senha'], "qrcode": True}, 
                                      headers={"apikey": EVO_API_KEY})

                        # Configura Webhook
                        webhook_url = f"{DOMAIN_URL}/webhook/whatsapp"
                        requests.post(f"{EVO_API_URL}/webhook/set/{user['instancia_wa']}", 
                                      json={"webhook": {"enabled": True, "url": webhook_url, "events": ["MESSAGES_UPSERT"]}}, 
                                      headers={"apikey": EVO_API_KEY})
                        print("🚀 Instância criada automaticamente!")
                    except Exception as evo_err:
                        print(f"⚠️ Erro ao criar instância auto: {evo_err}")

                conn.close()

        return {"status": "ok"}
    except Exception as e:
        print(f"Erro Webhook MP: {e}")
        return {"status": "error"}


# ==============================================================================
# WEBHOOK BLINDADO (CORREÇÃO DE MISTURA DE INSTÂNCIAS) 🛡️
# ==============================================================================

# Variável Global de Estado (Memória do Robô)
user_state = {} 

@app.post("/webhook/{instancia_rota}")
async def receber_webhook(instancia_rota: str, request: Request):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        body = await request.json()
        
        # --- 1. FILTROS ---
        evento = body.get("event", "")
        if evento != "messages.upsert": return {"status": "ignored_event"}
        
        data = body.get("data", {})
        key = data.get("key", {})
        remote_jid = key.get("remoteJid")
        from_me = key.get("fromMe", False)
        
        # Garante que a instancia seja uma string limpa
        instancia = str(body.get("instance") or instancia_rota).strip()

        if from_me: return {"status": "ignored_me"} 

        # --- CHAVE DE ESTADO ÚNICA (PREVINE MISTURA DE CLIENTES) ---
        # Antes era só remote_jid. Agora é instancia + remote_jid
        state_key = f"{instancia}-{remote_jid}"

        # --- 2. EXTRAÇÃO DE TEXTO ---
        msg_text = ""
        msg_type = data.get("messageType", "unknown")
        content = data.get("message", {})

        if msg_type == "conversation":
            msg_text = content.get("conversation", "")
        elif msg_type == "extendedTextMessage":
            msg_text = content.get("extendedTextMessage", {}).get("text", "")
        elif msg_type == "buttonsResponseMessage":
            msg_text = content.get("buttonsResponseMessage", {}).get("selectedDisplayText", "")
        elif msg_type == "listResponseMessage":
            msg_text = content.get("listResponseMessage", {}).get("title", "")
        elif msg_type == "imageMessage":
            msg_text = content.get("imageMessage", {}).get("caption", "[Imagem]")
        
        if not msg_text: return {"status": "no_text"}

        push_name = data.get("pushName") or "Cliente"
        msg_clean = msg_text.strip()
        msg_lower = msg_clean.lower()
        
        print(f"📩 [{instancia}] {push_name}: {msg_clean}")

        # --- 3. CRM (SEGREGADO POR INSTÂNCIA) ---
        try:
            cur.execute("SELECT id FROM clientes_finais WHERE instancia = %s AND telefone = %s", (instancia, remote_jid))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO clientes_finais (instancia, nome, telefone, dia_vencimento, etiquetas)
                    VALUES (%s, %s, %s, 1, 'captura_automatica')
                """, (instancia, push_name, remote_jid))
                conn.commit()
        except: 
            conn.rollback()

        # --- 4. VERIFICA BLOQUEIO DE ATENDENTE HUMANO (SEGREGADO) ---
        cur.execute("SELECT id FROM atendimentos WHERE instancia = %s AND remote_jid = %s AND status != 'finalizado'", (instancia, remote_jid))
        atendimento = cur.fetchone()

        if atendimento:
            if msg_lower in ["/encerrar", "/voltar", "/bot", "sair do suporte"]:
                cur.execute("DELETE FROM atendimentos WHERE id = %s", (atendimento['id'],))
                conn.commit()
                requests.post(f"{EVO_API_URL}/message/sendText/{instancia}", 
                              json={"number": remote_jid, "text": "🤖 Robô reativado! Digite 'Oi' para ver o menu."}, 
                              headers={"apikey": EVO_API_KEY})
                return {"status": "bot_reactivated"}
            else:
                print(f"🔇 Silenciado (Humano): {remote_jid} na instância {instancia}")
                return {"status": "human_mode"}

        # --- 5. GATILHO DE TRANSBORDO ---
        palavras_humanas = ["atendente", "falar com humano", "suporte", "pessoa"]
        if any(p in msg_lower for p in palavras_humanas):
            try:
                cur.execute("SELECT id FROM atendimentos WHERE instancia = %s AND remote_jid = %s AND status != 'finalizado'", (instancia, remote_jid))
                if not cur.fetchone():
                    cur.execute("INSERT INTO atendimentos (instancia, remote_jid, status) VALUES (%s, %s, 'pendente')", (instancia, remote_jid))
                    conn.commit()
                    requests.post(f"{EVO_API_URL}/message/sendText/{instancia}", 
                                  json={"number": remote_jid, "text": "🔔 Um atendente foi notificado. Aguarde... (Digite /voltar para cancelar)"}, 
                                  headers={"apikey": EVO_API_KEY})
                    return {"status": "handed_off"}
                else:
                    return {"status": "already_in_queue"}
            except: 
                conn.rollback()

        # ======================================================================
        # 🤖 LÓGICA DO ROBÔ (AGORA COM FILTRO RÍGIDO DE INSTÂNCIA)
        # ======================================================================

        resposta_db = None
        novo_estado_id = None
        limpar_estado = False

        # A. COMANDO RESET
        if msg_lower in ["oi", "ola", "olá", "menu", "inicio", "início", "começar"]:
            if state_key in user_state: del user_state[state_key]
            # Busca default APENAS desta instância
            cur.execute("SELECT * FROM respostas_automacao WHERE gatilho = 'default' AND instancia = %s", (instancia,))
            resposta_db = cur.fetchone()
        
        # B. COMANDO VOLTAR
        elif msg_lower == "voltar":
            estado_atual = user_state.get(state_key)
            if estado_atual:
                cur.execute("SELECT id_pai FROM respostas_automacao WHERE id = %s AND instancia = %s", (estado_atual, instancia))
                pai = cur.fetchone()
                if pai and pai['id_pai']:
                    cur.execute("SELECT * FROM respostas_automacao WHERE id = %s AND instancia = %s", (pai['id_pai'], instancia))
                    resposta_db = cur.fetchone()
                else:
                    if state_key in user_state: del user_state[state_key]
                    cur.execute("SELECT * FROM respostas_automacao WHERE gatilho = 'default' AND instancia = %s", (instancia,))
                    resposta_db = cur.fetchone()
            else:
                cur.execute("SELECT * FROM respostas_automacao WHERE gatilho = 'default' AND instancia = %s", (instancia,))
                resposta_db = cur.fetchone()

        # C. BUSCA NORMAL
        else:
            estado_atual = user_state.get(state_key)
            
            # Busca Filho
            if estado_atual:
                cur.execute("""
                    SELECT * FROM respostas_automacao 
                    WHERE instancia = %s AND id_pai = %s AND gatilho ILIKE %s
                """, (instancia, estado_atual, msg_clean))
                resposta_db = cur.fetchone()
            
            # Busca Raiz (Sem pai)
            if not resposta_db:
                cur.execute("""
                    SELECT * FROM respostas_automacao 
                    WHERE instancia = %s AND id_pai IS NULL AND gatilho ILIKE %s
                """, (instancia, msg_clean))
                resposta_db = cur.fetchone()

        # --- PROCESSAMENTO ---
        if resposta_db:
            print(f"✅ Menu Encontrado: '{resposta_db['gatilho']}' para instância {instancia}")

            # 1. BUSCA SUB-MENUS (AQUI ESTAVA O PERIGO - AGORA TEM FILTRO)
            # Adicionei 'AND instancia = %s' para impedir que pegue filhos de outro cliente
            cur.execute("""
                SELECT gatilho, titulo_menu 
                FROM respostas_automacao 
                WHERE id_pai = %s AND instancia = %s 
                ORDER BY id ASC
            """, (resposta_db['id'], instancia))
            opcoes_filhas = cur.fetchall()
            
            texto_final = resposta_db['resposta']
            
            if opcoes_filhas:
                novo_estado_id = resposta_db['id']
                texto_final += "\n\n"
                for opt in opcoes_filhas:
                    lbl = opt['titulo_menu'] if opt['titulo_menu'] else opt['gatilho'].capitalize()
                    texto_final += f"▪️ *{opt['gatilho']}* - {lbl}\n"
            else:
                limpar_estado = True

            # 2. Atualiza Memória (Usando a chave composta)
            if novo_estado_id:
                user_state[state_key] = novo_estado_id
            if limpar_estado and state_key in user_state:
                del user_state[state_key]

            # 3. Envia Texto
            payload_txt = {"number": remote_jid, "text": texto_final, "delay": 1200, "linkPreview": True}
            url_envio = f"{EVO_API_URL}/message/sendText/{instancia}"
            
            try:
                r = requests.post(url_envio, json=payload_txt, headers={"apikey": EVO_API_KEY}, timeout=10)
                if r.status_code not in [200, 201]:
                    print(f"❌ Erro Evolution: {r.text}")
            except Exception as e:
                print(f"❌ Falha Conexão Envio: {e}")

            # 4. Envia Mídia
            url_midia = resposta_db.get('url_midia')
            if url_midia and len(url_midia) > 5:
                try:
                    nome_arquivo = url_midia.split("/")[-1]
                    caminho_local = f"uploads/{nome_arquivo}"
                    
                    if os.path.exists(caminho_local):
                        with open(caminho_local, "rb") as f:
                            base64_media = base64.b64encode(f.read()).decode('utf-8')
                        
                        ext = nome_arquivo.split('.')[-1].lower()
                        mime_type = "image/jpeg"
                        media_type = "image"
                        if ext == "pdf": mime_type="application/pdf"; media_type="document"
                        elif ext == "mp4": mime_type="video/mp4"; media_type="video"
                        elif ext == "png": mime_type="image/png"

                        payload_media = {
                            "number": remote_jid,
                            "media": base64_media,
                            "mediatype": media_type,
                            "mimetype": mime_type,
                            "caption": resposta_db['resposta'],
                            "fileName": nome_arquivo
                        }
                        
                        requests.post(f"{EVO_API_URL}/message/sendMedia/{instancia}", 
                                      json=payload_media, 
                                      headers={"apikey": EVO_API_KEY})
                except Exception as e_midia:
                    print(f"❌ Erro ao enviar mídia: {e_midia}")

        else:
            # OPÇÃO INVÁLIDA
            estado_atual = user_state.get(state_key)
            if estado_atual:
                cur.execute("SELECT resposta FROM respostas_automacao WHERE id = %s AND instancia = %s", (estado_atual, instancia))
                pai = cur.fetchone()
                
                # Remonta apenas com filhos DA MESMA INSTÂNCIA
                cur.execute("""
                    SELECT gatilho, titulo_menu 
                    FROM respostas_automacao 
                    WHERE id_pai = %s AND instancia = %s 
                    ORDER BY id ASC
                """, (estado_atual, instancia))
                opcoes = cur.fetchall()
                
                msg_erro = "❌ Opção inválida. Tente:\n\n"
                for opt in opcoes:
                    lbl = opt['titulo_menu'] if opt['titulo_menu'] else opt['gatilho'].capitalize()
                    msg_erro += f"▪️ *{opt['gatilho']}* - {lbl}\n"
                
                requests.post(f"{EVO_API_URL}/message/sendText/{instancia}", 
                              json={"number": remote_jid, "text": msg_erro}, 
                              headers={"apikey": EVO_API_KEY})

        return {"status": "processed"}

    except Exception as e:
        print(f"💥 ERRO CRÍTICO: {e}")
        return {"status": "error"}
    finally:
        if conn:
            cur.close()
            conn.close()

# --- ROTA DE MÉTRICAS PARA O DASHBOARD ---
@app.get("/metricas/{instancia}")
def obter_metricas(instancia: str):
    print(f"📊 Calculando métricas para: '{instancia}'") # Debug
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # 1. TOTAL DE MENSAGENS
        cur.execute("SELECT COUNT(*) FROM chat_logs WHERE instancia = %s AND from_me = TRUE", (instancia,))
        total_msgs = cur.fetchone()['count']
        print(f"   -> Msgs Bot: {total_msgs}")

        # 2. TOTAL DE CLIENTES
        cur.execute("SELECT COUNT(*) FROM clientes_finais WHERE instancia = %s", (instancia,))
        total_clientes = cur.fetchone()['count']
        print(f"   -> Clientes: {total_clientes}")

        # 3. NOVOS (Tenta com data_cadastro, se falhar usa 0)
        novos_mes = 0
        try:
            hoje = datetime.now()
            primeiro_dia = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            cur.execute("""
                SELECT COUNT(*) FROM clientes_finais 
                WHERE instancia = %s AND data_cadastro >= %s
            """, (instancia, primeiro_dia))
            novos_mes = cur.fetchone()['count']
        except Exception as e:
            print(f"⚠️ Erro ao calcular novos (falta coluna data_cadastro?): {e}")
            conn.rollback() # Destrava o banco

        # 4. GATILHOS
        cur.execute("SELECT COUNT(*) FROM respostas_automacao WHERE instancia = %s", (instancia,))
        total_gatilhos = cur.fetchone()['count']

        # 5. GRÁFICO DIÁRIO
        data_limite = datetime.now() - timedelta(days=7)
        cur.execute("""
            SELECT DATE(data_hora) as dia, COUNT(*) as qtd 
            FROM chat_logs 
            WHERE instancia = %s AND data_hora >= %s 
            GROUP BY dia ORDER BY dia
        """, (instancia, data_limite))
        dados_grafico = cur.fetchall()
        grafico_fmt = [{"Data": str(d['dia']), "Mensagens": d['qtd']} for d in dados_grafico]

        # 6. ETIQUETAS
        cur.execute("""
            SELECT etiquetas, COUNT(*) as qtd 
            FROM clientes_finais 
            WHERE instancia = %s 
            GROUP BY etiquetas
        """, (instancia,))
        dados_etiquetas = cur.fetchall()
        
        etiquetas_fmt = []
        for item in dados_etiquetas:
            nome_tag = item['etiquetas'] if item['etiquetas'] else "Sem Etiqueta"
            etiquetas_fmt.append({"Etiqueta": nome_tag, "Quantidade": item['qtd']})

        conn.close()
        
        return {
            "total_mensagens_bot": total_msgs,
            "total_clientes": total_clientes,
            "novos_clientes_mes": novos_mes,
            "total_gatilhos": total_gatilhos,
            "grafico_mensagens": grafico_fmt,
            "grafico_etiquetas": etiquetas_fmt
        }
        
    except Exception as e:
        print(f"💥 ERRO GERAL MÉTRICAS: {e}")
        return {"total_clientes": 0, "erro": str(e)}
    
# ==============================================================================
# 3. ROTAS DE CADASTRO E LOGIN (NECESSÁRIAS PARA O PAINEL)
# ==============================================================================

# --- CONFIGURAÇÃO DOS LIMITES ---
LIMITES = {
    "Básico": {"max_gatilhos": 5, "permite_midia": False},
    "Pro": {"max_gatilhos": 99999, "permite_midia": True},
    "Enterprise": {"max_gatilhos": 99999, "permite_midia": True}
}

@app.post("/salvar")
async def salvar_gatilho(item: Gatilho):
    try:
        conn = get_connection()
        cur = conn.cursor()

        # 1. DESCOBRIR O PLANO DO CLIENTE
        cur.execute("SELECT plano FROM usuarios WHERE instancia_wa = %s", (item.instancia,))
        user_data = cur.fetchone()
        
        # Se não achar o plano, assume o Básico por segurança
        plano_atual = user_data[0] if user_data and user_data[0] else "Básico"
        regras = LIMITES.get(plano_atual, LIMITES["Básico"])

        # 2. VERIFICAR SE O GATILHO JÁ EXISTE (Para saber se é Edição ou Criação)
        cur.execute("""
            SELECT id FROM respostas_automacao 
            WHERE instancia=%s AND gatilho=%s AND id_pai IS NOT DISTINCT FROM %s
        """, (item.instancia, item.gatilho, item.id_pai))
        existe = cur.fetchone()

        # 3. BLOQUEIO DE MÍDIA (Se tentar salvar mídia no plano Básico)
        if item.url_midia and not regras["permite_midia"]:
             # Se for edição e já tinha mídia, deixa passar (ou bloqueia, você decide). 
             # Aqui vou bloquear qualquer tentativa de salvar mídia nova.
             raise HTTPException(status_code=403, detail=f"O plano {plano_atual} não permite envio de mídia (Áudio/Imagem/Vídeo). Faça um Upgrade!")

        # 4. BLOQUEIO DE QUANTIDADE (Só verifica se for NOVO cadastro)
        if not existe:
            cur.execute("SELECT COUNT(*) FROM respostas_automacao WHERE instancia = %s", (item.instancia,))
            qtd_atual = cur.fetchone()[0]
            
            if qtd_atual >= regras["max_gatilhos"]:
                raise HTTPException(status_code=403, detail=f"Você atingiu o limite de {regras['max_gatilhos']} gatilhos do plano {plano_atual}. Contrate o Pro!")

        # --- SE PASSOU NOS TESTES, GRAVA NO BANCO ---
        if existe:
             # UPDATE
             cur.execute("""
                UPDATE respostas_automacao SET 
                resposta=%s, tipo_midia=%s, url_midia=%s, id_pai=%s, titulo_menu=%s, categoria=%s
                WHERE id=%s
             """, (item.resposta, item.tipo_midia, item.url_midia, item.id_pai, item.titulo_menu, item.categoria, existe[0]))
        else:
            # INSERT
            cur.execute("""
                INSERT INTO respostas_automacao 
                (instancia, gatilho, resposta, titulo_menu, categoria, tipo_midia, url_midia, id_pai) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (item.instancia, item.gatilho, item.resposta, item.titulo_menu, item.categoria, item.tipo_midia, item.url_midia, item.id_pai))
        
        conn.commit()
        conn.close()
        return {"status": "sucesso"}

    except HTTPException as he:
        raise he # Repassa o erro de permissão para o painel
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/listar/{instancia}")
async def listar_gatilhos(instancia: str):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, gatilho, resposta, tipo_midia, url_midia, id_pai FROM respostas_automacao WHERE instancia = %s ORDER BY id_pai ASC, id ASC", (instancia,))
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []

@app.delete("/excluir/{id}")
async def excluir_gatilho(id: int):
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Deleta filhos primeiro para não dar erro de chave estrangeira
        cur.execute("DELETE FROM respostas_automacao WHERE id_pai = %s", (id,))
        cur.execute("DELETE FROM respostas_automacao WHERE id = %s", (id,))
        conn.commit()
        conn.close()
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_arquivo(file: UploadFile = File(...)):
    with open(f"uploads/{file.filename}", "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # Retorna URL HTTPS para o WhatsApp conseguir baixar
    return {"url": f"{DOMAIN_URL}/arquivos/{file.filename}"}

# --- 1. LOGIN HÍBRIDO ATUALIZADO (Dono + Atendente + Vencimento) ---
@app.post("/login")
async def login(dados: dict):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        login_input = dados['login']
        senha_input = dados['senha']

        # ==========================================================
        # TENTATIVA 1: É UM DONO (USUÁRIO ADMIN)?
        # ==========================================================
        cur.execute("""
            SELECT id, nome_cliente, login, senha, instancia_wa, status_conta, plano, valor_mensal, data_vencimento 
            FROM usuarios WHERE login = %s
        """, (login_input,))
        user = cur.fetchone()

        # Se achou usuário E a senha bate
        if user and user['senha'] == senha_input:
            
            # --- LÓGICA DE VENCIMENTO (DO DONO) ---
            if user['data_vencimento']:
                hoje = date.today()
                vencimento = user['data_vencimento']
                
                if hoje > vencimento:
                    cur.execute("UPDATE usuarios SET status_conta = 'vencido' WHERE id = %s", (user['id'],))
                    conn.commit()
                    user['status_conta'] = 'vencido'

            # Define papel como ADMIN
            user['role'] = 'admin'
            
            # Tratamento de Tipos para JSON
            if user.get('valor_mensal'): user['valor_mensal'] = float(user['valor_mensal'])
            if user.get('data_vencimento'): user['data_vencimento'] = str(user['data_vencimento'])

            return {"status": "sucesso", "usuario": user}

        # ==========================================================
        # TENTATIVA 2: É UM ATENDENTE (FUNCIONÁRIO)?
        # ==========================================================
        # Só entra aqui se não logou como dono
        cur.execute("SELECT * FROM atendentes WHERE login = %s", (login_input,))
        atendente = cur.fetchone()

        if atendente and atendente['senha'] == senha_input:
            
            # Busca dados do CHEFE (Dono da conta)
            # O atendente precisa da instância e do status do chefe para trabalhar
            cur.execute("""
                SELECT id, instancia_wa, plano, status_conta, data_vencimento 
                FROM usuarios WHERE id = %s
            """, (atendente['usuario_id'],))
            chefe = cur.fetchone()

            if not chefe:
                raise HTTPException(status_code=401, detail="Conta do administrador vinculada não encontrada.")

            # --- LÓGICA DE VENCIMENTO (DO CHEFE) ---
            # Se o chefe estiver vencido, o atendente não pode logar
            if chefe['data_vencimento']:
                hoje = date.today()
                if hoje > chefe['data_vencimento']:
                    # Atualiza o banco do chefe se necessário
                    cur.execute("UPDATE usuarios SET status_conta = 'vencido' WHERE id = %s", (chefe['id'],))
                    conn.commit()
                    chefe['status_conta'] = 'vencido'

            # Monta o Perfil Híbrido (Dados do Atendente + Contexto do Chefe)
            perfil_atendente = {
                "id": atendente['id'],               # ID único do atendente
                "usuario_id": chefe['id'],           # ID do chefe
                "nome_cliente": atendente['nome'],   # Nome do atendente
                "login": atendente['login'],
                "role": "atendente",                 # <--- IMPORTANTE: Define o papel
                "instancia_wa": chefe['instancia_wa'], # Herda instância do chefe
                "plano": chefe['plano'],             # Herda plano do chefe
                "status_conta": chefe['status_conta'] # Herda status (ativo/vencido)
            }

            return {"status": "sucesso", "usuario": perfil_atendente}

        # ==========================================================
        # FALHA TOTAL (Não achou nem Dono nem Atendente)
        # ==========================================================
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro Login: {e}")
        conn.rollback() # Garante rollback em caso de erro SQL
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# --- 2. GESTÃO DE CUPONS (Admin) ---
@app.get("/cupons")
def listar_cupons():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM cupons")
    cupons = cur.fetchall()
    conn.close()
    return cupons

@app.post("/cupons")
def criar_cupom(dados: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO cupons (codigo, desconto_porcentagem) VALUES (%s, %s)", 
                   (dados['codigo'].upper(), dados['desconto']))
        conn.commit()
        return {"status": "criado"}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}
    finally:
        conn.close()

@app.delete("/cupons/{codigo}")
def deletar_cupom(codigo: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM cupons WHERE codigo = %s", (codigo,))
    conn.commit()
    conn.close()
    return {"status": "deletado"}


# --- 3. RENOVAÇÃO / UPGRADE (Cliente Logado) ---
@app.post("/pagamento/gerar")
async def gerar_pagamento_usuario(dados: dict):
    # dados espera: { "user_id": 1, "plano": "Pro", "valor": 99.90, "cupom": "CODIGO" }
    print(f"🔄 Processando renovação para User ID {dados['user_id']}")
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Pega dados do usuário
        cur.execute("SELECT * FROM usuarios WHERE id = %s", (dados['user_id'],))
        user = cur.fetchone()
        
        # Define valor base (Segurança: idealmente pegaria da tabela PRECOS_OFICIAIS, mas vamos usar o enviado por enquanto)
        valor_final = float(dados['valor'])
        cupom_aplicado_txt = ""

        # --- LÓGICA DO CUPOM ---
        if dados.get('cupom'):
            codigo = dados['cupom'].strip().upper()
            cur.execute("SELECT desconto_porcentagem FROM cupons WHERE codigo = %s AND ativo = TRUE", (codigo,))
            res_cupom = cur.fetchone()
            
            if res_cupom:
                desconto = res_cupom['desconto_porcentagem']
                desconto_reais = (valor_final * desconto) / 100
                valor_final = valor_final - desconto_reais
                cupom_aplicado_txt = f"- Cupom {codigo} ({desconto}%)"
                print(f"🎟️ Cupom {codigo} aplicado na renovação!")
            else:
                print(f"⚠️ Cupom de renovação inválido: {codigo}")
        
        valor_final = round(valor_final, 2)
        # -----------------------

        # SE VALOR FOR ZERO (100% OFF)
        if valor_final <= 0:
            print("🎁 Renovação Gratuita (100% OFF)")
            # Renova por 30 dias a partir de HOJE (ou soma a data atual se quiser acumular, aqui vamos resetar pra 30 dias)
            cur.execute("""
                UPDATE usuarios SET 
                status_conta='ativo', 
                data_vencimento = CURRENT_DATE + INTERVAL '30 days', 
                plano=%s,
                valor_mensal=%s
                WHERE id=%s
            """, (dados['plano'], 0.00, user['id']))
            conn.commit()
            conn.close()
            return {"status": "aprovado_direto", "mensagem": "Plano renovado com sucesso (100% OFF)!"}

        # SE TIVER VALOR, GERA PIX NO MERCADO PAGO
        payment_data = {
            "transaction_amount": valor_final,
            "description": f"Renovação {dados['plano']} - {user['nome_cliente']} {cupom_aplicado_txt}",
            "payment_method_id": "pix",
            "payer": {"email": user['email'] or "cliente@email.com", "first_name": user['nome_cliente']},
            "notification_url": f"{DOMAIN_URL}/webhook/pagamento"
        }
        
        print(f"📡 Gerando Pix Renovação: R$ {valor_final}")
        resp = sdk_mp.payment().create(payment_data)
        pagamento = resp.get("response", {})
        
        if resp["status"] not in [200, 201]:
             err_msg = pagamento.get('message', 'Erro MP')
             raise HTTPException(status_code=400, detail=f"Erro Mercado Pago: {err_msg}")
             
        # Salva o ID do pagamento novo para o Webhook reconhecer depois
        # Importante: Atualizamos o valor_mensal para o novo valor com desconto
        cur.execute("UPDATE usuarios SET id_pagamento_mp = %s, plano = %s, valor_mensal = %s WHERE id = %s", 
                   (str(pagamento['id']), dados['plano'], valor_final, user['id']))
        conn.commit()
        conn.close()
        
        return {
            "status": "aguardando",
            "qr_code": pagamento['point_of_interaction']['transaction_data']['qr_code'],
            "qr_base64": pagamento['point_of_interaction']['transaction_data']['qr_code_base64'],
            "valor_final": valor_final
        }

    except Exception as e:
        print(f"Erro Renovação: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/usuarios/cadastrar")
async def cadastrar_usuario(dados: dict):
    print(f"📝 Iniciando cadastro: {dados['login']}")

    # --- PASSO 1 E 2: EVOLUTION (MANTENHA SEU CÓDIGO AQUI) ---
    # (Estou resumindo para focar no banco, mas não apague a parte da Evolution!)
    try:
        url_create = f"{EVO_API_URL}/instance/create"
        payload_create = {
            "instanceName": dados['instancia_wa'],
            "token": dados['senha'], 
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS"
        }
        resp = requests.post(url_create, json=payload_create, headers={"apikey": EVO_API_KEY})
        
        # Configura Webhook
        webhook_url = f"{DOMAIN_URL}/webhook/whatsapp"
        requests.post(f"{EVO_API_URL}/webhook/set/{dados['instancia_wa']}", 
                      json={"webhook": {"enabled": True, "url": webhook_url, "events": ["MESSAGES_UPSERT"]}}, 
                      headers={"apikey": EVO_API_KEY})
    except Exception as e:
        print(f"⚠️ Erro Evolution: {e}")

    # --- PASSO 3: SALVAR NO BANCO (ATUALIZADO) ---
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Agora salvamos whatsapp e email também
        cur.execute("""
            INSERT INTO usuarios (login, senha, instancia_wa, nome_cliente, plano, valor_mensal, data_vencimento, whatsapp, email) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            dados['login'], dados['senha'], dados['instancia_wa'], dados['nome_cliente'], 
            dados['plano'], dados.get('valor_mensal', 0), dados.get('data_vencimento', None),
            dados.get('whatsapp', ''), dados.get('email', '')
        ))
        
        conn.commit()
        conn.close()
        return {"status": "sucesso"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/usuarios/listar")
async def listar_usuarios():
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # SQL ATUALIZADO: Trazendo plano, valor, vencimento, zap e email
        # O COALESCE serve para garantir que se estiver vazio (NULL), venha um valor padrão
        cur.execute("""
            SELECT 
                id, 
                login, 
                senha,
                instancia_wa, 
                nome_cliente,
                COALESCE(plano, 'Básico') as plano,
                COALESCE(valor_mensal, 0.00) as valor_mensal,
                data_vencimento,
                COALESCE(whatsapp, '') as whatsapp,
                COALESCE(email, '') as email
            FROM usuarios
            ORDER BY id ASC
        """)
        
        users = cur.fetchall()
        conn.close()
        return users
    except Exception as e:
        print(f"Erro ao listar: {e}")
        return []
    
@app.delete("/usuarios/excluir/{id}")
async def excluir_usuario(id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM usuarios WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return {"status": "sucesso"}

@app.post("/verificar_gatilho")
async def verificar_gatilho(dados: ConsultaGatilho):
    # Simulador do Painel
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM respostas_automacao WHERE instancia = %s AND gatilho ILIKE %s", (dados.instancia, dados.mensagem.strip()))
    res = cur.fetchone()
    conn.close()
    if res:
        return {"encontrou": True, "resposta": res['resposta'], "tipo_midia": res['tipo_midia'], "url_midia": res['url_midia']}
    else:
        return {"encontrou": False, "resposta": "Não entendi."}

# --- ROTAS DE TRANSBORDO ---
# NO SEU ARQUIVO MAIN.PY

@app.get("/atendimentos/{instancia}")
def listar_atendimentos(instancia: str):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        print(f"--- DEBUG BACKEND ---")
        print(f"1. Buscando pela instância: '{instancia}'")

        # PRIMEIRO: Vamos ver se tem ALGUMA COISA na tabela (sem filtro)
        # Isso ajuda a saber se estamos conectados no banco certo
        cur.execute("SELECT instancia, status FROM atendimentos LIMIT 5")
        geral = cur.fetchall()
        print(f"2. O que tem no banco agora (Amostra): {geral}")

        # SEGUNDO: A Busca Real (Com TRIM para ignorar espaços)
        # Usamos TRIM(instancia) para ignorar espaços no banco
        cur.execute("""
            SELECT * FROM atendimentos 
            WHERE TRIM(instancia) = %s AND status != 'finalizado'
            ORDER BY data_inicio ASC
        """, (instancia.strip(),)) # .strip() remove espaços da requisição
        
        fila = cur.fetchall()
        print(f"3. Resultado da busca exata: {len(fila)} encontrados.")
        print(f"---------------------")
        
        # Converte datas
        for item in fila:
            if item.get('data_inicio'):
                item['data_inicio'] = str(item['data_inicio'])
        
        return fila

    except Exception as e:
        print(f"ERRO SQL: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})
    finally:
        conn.close()

@app.delete("/atendimentos/{id}")
def encerrar_atendimento(id: int):
    conn = get_connection()
    cur = conn.cursor()
    # Pega os dados antes de apagar para mandar mensagem de aviso
    cur.execute("SELECT instancia, remote_jid FROM atendimentos_ativos WHERE id = %s", (id,))
    item = cur.fetchone()
    
    if item:
        instancia, remote_jid = item
        # Apaga
        cur.execute("DELETE FROM atendimentos_ativos WHERE id = %s", (id,))
        conn.commit()
        
        # Opcional: Avisa o cliente
        enviar_mensagem_smart(instancia, remote_jid, "✅ O atendimento humano foi finalizado. O robô assumiu novamente.")
        
    conn.close()
    return {"status": "ok"}


@app.put("/usuarios/editar/{user_id}")
async def editar_usuario(user_id: int, dados: dict):
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Atualiza os dados do cliente
        cur.execute("""
            UPDATE usuarios SET 
            nome_cliente=%s, login=%s, senha=%s, plano=%s, 
            valor_mensal=%s, data_vencimento=%s, whatsapp=%s, email=%s
            WHERE id=%s
        """, (
            dados['nome_cliente'], dados['login'], dados['senha'], 
            dados['plano'], dados['valor_mensal'], dados['data_vencimento'],
            dados.get('whatsapp', ''), dados.get('email', ''),
            user_id
        ))
        
        conn.commit()
        conn.close()
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# =====================================================
# 📂 CRM & DISPAROS (NOVO)
# =====================================================

# 1. ATUALIZAR CLIENTE (NOVA ROTA)
@app.put("/crm/clientes/{id}")
def atualizar_cliente_final(id: int, dados: dict):
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Monta a query dinâmica (só atualiza o que vier)
        # Nota: dia_vencimento pode vir None
        cur.execute("""
            UPDATE clientes_finais 
            SET nome = %s, dia_vencimento = %s, etiquetas = %s
            WHERE id = %s
        """, (dados['nome'], dados.get('dia_vencimento'), dados.get('etiquetas'), id))
        
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    
# 1. Cadastrar Cliente Final
@app.post("/crm/clientes")
def cadastrar_cliente_final(dados: dict):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes_finais (instancia, nome, telefone, dia_vencimento, etiquetas)
            VALUES (%s, %s, %s, %s, %s)
        """, (dados['instancia'], dados['nome'], dados['telefone'], dados['dia_vencimento'], dados['etiquetas']))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}



# 3. Excluir Cliente
@app.delete("/crm/clientes/{id}")
def excluir_cliente_final(id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM clientes_finais WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


# 2. LISTAR COM PAGINAÇÃO (MODIFICADA)
@app.get("/crm/clientes/{instancia}")
def listar_clientes_finais(instancia: str, pagina: int = 1, itens_por_pagina: int = 50, busca: str = None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    offset = (pagina - 1) * itens_por_pagina
    
    # Query Base
    sql_base = "FROM clientes_finais WHERE instancia = %s"
    params = [instancia]
    
    # Filtro de Busca (Nome ou Telefone)
    if busca:
        sql_base += " AND (nome ILIKE %s OR telefone ILIKE %s)"
        params.extend([f"%{busca}%", f"%{busca}%"])
    
    # 1. Conta Total (para saber quantas páginas existem)
    cur.execute(f"SELECT COUNT(*) {sql_base}", tuple(params))
    total_itens = cur.fetchone()['count']
    
    # 2. Busca os Itens da Página
    cur.execute(f"SELECT * {sql_base} ORDER BY id DESC LIMIT %s OFFSET %s", tuple(params + [itens_por_pagina, offset]))
    itens = cur.fetchall()
    
    conn.close()
    
    return {
        "data": itens,
        "total": total_itens,
        "pagina_atual": pagina,
        "total_paginas": -(-total_itens // itens_por_pagina) # Arredonda pra cima
    }

# 4. 🚀 O DISPARADOR EM MASSA
@app.post("/disparo/em-massa")
def disparo_em_massa(dados: dict):
    instancia = dados['instancia']
    texto_base = dados['mensagem']
    lista_ids = dados['lista_ids']
    incluir_menu = dados.get('incluir_menu', False)
    
    # NOVOS CAMPOS PARA MÍDIA
    url_midia = dados.get('url_midia')     # Ex: http://.../uploads/foto.jpg
    tipo_midia = dados.get('tipo_midia')   # image, video, document
    
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    if not lista_ids: return {"status": "vazio"}
    
    format_strings = ','.join(['%s'] * len(lista_ids))
    cur.execute(f"SELECT nome, telefone FROM clientes_finais WHERE id IN ({format_strings})", tuple(lista_ids))
    destinatarios = cur.fetchall()
    conn.close()
    
    enviados = 0
    erros = 0
    
    # ---------------------------------------------------------
    # PREPARAÇÃO DA MÍDIA (SE HOUVER)
    # ---------------------------------------------------------
    base64_midia = None
    nome_arquivo = "arquivo"
    mimetype = "image/jpeg" # Padrão
    
    if url_midia:
        try:
            # Pega o nome do arquivo da URL (ex: .../uploads/promo.jpg -> promo.jpg)
            nome_arquivo = url_midia.split("/")[-1]
            caminho_local = f"uploads/{nome_arquivo}"
            
            # Lê o arquivo do disco e converte pra Base64 UMA VEZ SÓ (Performance 🚀)
            if os.path.exists(caminho_local):
                with open(caminho_local, "rb") as f:
                    base64_midia = base64.b64encode(f.read()).decode('utf-8')
                
                # Define mimetype básico
                ext = nome_arquivo.split('.')[-1].lower()
                if ext == "png": mimetype = "image/png"
                elif ext == "pdf": mimetype = "application/pdf"
                elif ext == "mp4": mimetype = "video/mp4"
            else:
                print(f"⚠️ Arquivo não encontrado no servidor: {caminho_local}")
        except Exception as e:
            print(f"Erro ao processar mídia: {e}")

    print(f"🚀 Iniciando disparo (Mídia: {bool(base64_midia)})...")

    # ---------------------------------------------------------
    # LOOP DE ENVIO
    # ---------------------------------------------------------
    for pessoa in destinatarios:
        try:
            # Personaliza o texto
            msg_final = texto_base.replace("{nome}", pessoa['nome'])
            
            # Se pediu menu, anexa no final
            # (Aqui fazemos manual pq vamos usar sendMedia, não a função smart)
            if incluir_menu:
                # Nota: Buscar o menu no banco 500x é pesado. 
                # Idealmente buscaria fora do loop, mas vamos simplificar.
                msg_final += "\n\n(Digite 'Menu' para ver as opções)"

            # DECISÃO: MANDA MÍDIA OU TEXTO?
            if base64_midia:
                # ENVIA COM IMAGEM
                payload = {
                    "number": pessoa['telefone'],
                    "media": base64_midia,
                    "mediatype": tipo_midia,
                    "mimetype": mimetype,
                    "caption": msg_final, # O texto vira legenda
                    "fileName": nome_arquivo
                }
                requests.post(f"{EVO_API_URL}/message/sendMedia/{instancia}", json=payload, headers={"apikey": EVO_API_KEY})
            else:
                # ENVIA SÓ TEXTO (Usa a função smart que já temos, ou direto)
                # Vamos usar direto pra garantir controle total
                payload = {"number": pessoa['telefone'],"text": msg_final}
                requests.post(f"{EVO_API_URL}/message/sendText/{instancia}", json=payload, headers={"apikey": EVO_API_KEY})
            
            # Log (Opcional)
            # ... código de log aqui ...

            enviados += 1
            time.sleep(1) # Delay anti-bloqueio
            
        except Exception as e:
            print(f"Erro envio {pessoa['nome']}: {e}")
            erros += 1
            
    return {"status": "concluido", "enviados": enviados, "erros": erros}


# =====================================================
# 📥 IMPORTAÇÃO DE CONTATOS (VERSÃO CHAVE MESTRA 🗝️)
# =====================================================
@app.post("/crm/importar_whatsapp")
def importar_contatos_whatsapp(dados: dict):
    instancia = dados.get("instancia")
    headers = {"apikey": EVO_API_KEY, "Content-Type": "application/json"}
    
    print(f"📥 Iniciando varredura de rotas para: {instancia}")

    # Lista de todas as possibilidades conhecidas (Método, Endpoint)
    rotas_possiveis = [
        ("GET",  f"/chat/find/{instancia}"),          # Mais provável (v1.8+)
        ("GET",  f"/chat/retriever/{instancia}"),     # Alternativa comum
        ("GET",  f"/chat/findChats/{instancia}"),     # v2.0+ (já falhou, mas deixamos aqui)
        ("POST", f"/chat/find/{instancia}"),          # Antiga (já falhou, mas vai que...)
        ("GET",  f"/contact/find/{instancia}"),       # Contatos v1
        ("POST", f"/contact/find/{instancia}"),       # Contatos v1 (POST)
        ("GET",  f"/contact/findAll/{instancia}"),    # Contatos v2
    ]

    chats = []
    sucesso = False
    rota_funcionou = ""

    # --- LOOP DE TENTATIVAS ---
    for metodo, endpoint in rotas_possiveis:
        url = f"{EVO_API_URL}{endpoint}"
        print(f"🕵️ Testando: {metodo} {endpoint} ...", end="")
        
        try:
            if metodo == "GET":
                res = requests.get(url, headers=headers, timeout=10)
            else:
                res = requests.post(url, json={"where": {}}, headers=headers, timeout=10)
            
            if res.status_code == 200:
                print(" ✅ SUCESSO!")
                payload = res.json()
                
                # Normaliza o retorno (pode vir lista direta ou dict)
                if isinstance(payload, list):
                    chats = payload
                elif isinstance(payload, dict):
                    chats = payload.get('data') or payload.get('chats') or payload.get('contacts') or []
                
                sucesso = True
                rota_funcionou = endpoint
                break # Para o loop se funcionou
            else:
                print(f" ❌ ({res.status_code})")
                
        except Exception as e:
            print(f" ⚠️ Erro: {e}")

    # --- SE TUDO FALHAR ---
    if not sucesso:
        return {"status": "error", "detail": "Nenhuma rota compatível encontrada. Atualize sua Evolution API."}

    if not chats:
        return {"status": "error", "detail": "Rota encontrada, mas retornou lista vazia (sem conversas)."}

    print(f"🎉 Rota vencedora: {rota_funcionou} | Encontrados: {len(chats)}")

    # =====================================================
    # PROCESSAMENTO / BANCO
    # =====================================================
    try:
        conn = get_connection()
        cur = conn.cursor()

        importados = 0
        ignorados = 0

        for c in chats:
            # Tenta pegar ID de todas as formas possíveis
            jid = c.get("id") or c.get("jid") or c.get("remoteJid")
            if not jid and 'key' in c: jid = c['key'].get('remoteJid')

            # Tenta pegar Nome
            nome = c.get("pushName") or c.get("name") or c.get("verifiedName") or c.get("notify") or "Cliente WhatsApp"

            # 🛡️ Filtros
            if not jid: continue
            if "@g.us" in jid or "@broadcast" in jid or "status@" in jid: continue

            # Verifica duplicidade
            cur.execute("SELECT id FROM clientes_finais WHERE instancia=%s AND telefone=%s", (instancia, jid))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO clientes_finais (instancia, nome, telefone, dia_vencimento, etiquetas)
                    VALUES (%s, %s, %s, %s, %s)
                """, (instancia, nome, jid, NULL, "importado_whatsapp"))
                importados += 1
            else:
                ignorados += 1

        conn.commit()
        conn.close()

        return {"status": "ok", "novos": importados, "existentes": ignorados}

    except Exception as e:
        print(f"💥 Erro banco: {e}")
        return {"status": "error", "detail": str(e)}

# =====================================================
# ⚙️ ADMINISTRAÇÃO DE PLANOS
# =====================================================

# 1. LISTAR REGRAS (Para montar a tabela no painel)
@app.get("/admin/regras")
def listar_regras_planos():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cur.execute("SELECT * FROM regras_planos ORDER BY funcionalidade, plano")
    regras = cur.fetchall()
    
    conn.close()
    return regras

# 2. SALVAR REGRAS (Recebe a lista atualizada e salva)
@app.post("/admin/regras")
def atualizar_regras_planos(dados: dict):
    # O front vai mandar algo como: {"regras": [{"plano": "Básico", "func": "x", "ativo": true}, ...]}
    lista_regras = dados.get("regras", [])
    
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        for item in lista_regras:
            cur.execute("""
                INSERT INTO regras_planos (plano, funcionalidade, ativo)
                VALUES (%s, %s, %s)
                ON CONFLICT (plano, funcionalidade) 
                DO UPDATE SET ativo = EXCLUDED.ativo
            """, (item['plano'], item['funcionalidade'], item['ativo']))
        
        conn.commit()
        return {"status": "ok", "msg": "Regras atualizadas!"}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "detail": str(e)}
    finally:
        conn.close()

# 3. VERIFICADOR DE PERMISSÃO (Para você usar no código depois)
# Exemplo de uso: verificar_permissao('Básico', 'disparos_massa')
def verificar_permissao_backend(nome_plano, funcionalidade_chave):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT ativo FROM regras_planos WHERE plano = %s AND funcionalidade = %s", (nome_plano, funcionalidade_chave))
    res = cur.fetchone()
    conn.close()
    
    if res and res[0] == True:
        return True
    return False


# =====================================================
# VERIFICAÇÃO DE LIMITES DO PLANO 🚦
# =====================================================
@app.get("/automacao/verificar-limite/{instancia}")
def verificar_limite_automacao(instancia: str, plano: str):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Conta quantos gatilhos o usuário JÁ TEM
        cur.execute("SELECT COUNT(*) FROM respostas_automacao WHERE instancia = %s", (instancia,))
        qtd_atual = cur.fetchone()['count']

        # 2. Busca qual é o LIMITE do plano dele
        # (Se não achar regra, definimos um padrão seguro, ex: 5)
        cur.execute("""
            SELECT limite FROM regras_planos 
            WHERE plano = %s AND funcionalidade = 'max_gatilhos'
        """, (plano,))
        res_limite = cur.fetchone()
        
        # Se o plano for Enterprise ou não tiver limite definido, usamos 9999
        limite_max = res_limite['limite'] if res_limite else 5

        conn.close()

        return {
            "qtd_atual": qtd_atual,
            "limite_max": limite_max,
            "bloqueado": qtd_atual >= limite_max,
            "porcentagem": min(int((qtd_atual / limite_max) * 100), 100) if limite_max > 0 else 0
        }

    except Exception as e:
        return {"error": str(e), "bloqueado": True} # Na dúvida, bloqueia

# =====================================================
# 👥 GESTÃO DE EQUIPE (ATENDENTES)
# =====================================================

# 1. CRIAR ATENDENTE
@app.post("/equipe/criar")
def criar_atendente(dados: dict):
    # Payload: { "usuario_id": 1, "nome": "João", "login": "joao.loja", "senha": "123" }
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # Verifica se login já existe
        cur.execute("SELECT id FROM atendentes WHERE login = %s", (dados['login'],))
        if cur.fetchone():
            return JSONResponse(status_code=400, content={"detail": "Login já existe."})
            
        cur.execute("""
            INSERT INTO atendentes (usuario_id, nome, login, senha)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (dados['usuario_id'], dados['nome'], dados['login'], dados['senha']))
        
        conn.commit()
        return {"status": "ok", "id": cur.fetchone()[0]}
    except Exception as e:
        conn.rollback()
        return JSONResponse(status_code=500, content={"detail": str(e)})
    finally:
        conn.close()

# 2. LISTAR ATENDENTES DO DONO
@app.get("/equipe/listar/{usuario_id}")
def listar_equipe(usuario_id: int):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, nome, login, online FROM atendentes WHERE usuario_id = %s", (usuario_id,))
    res = cur.fetchall()
    conn.close()
    return res

# 3. EXCLUIR ATENDENTE
@app.delete("/equipe/excluir/{id}")
def excluir_atendente(id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM atendentes WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# =====================================================
# 📞 FILA DE ATENDIMENTO HUMANO
# =====================================================

# 1. LISTAR QUEM ESTÁ NA FILA (Para a tela do Atendente e do Admin)
@app.get("/atendimentos/{instancia}")
def listar_atendimentos(instancia: str):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Busca apenas quem NÃO foi finalizado (pendente ou em_andamento)
        cur.execute("""
            SELECT * FROM atendimentos 
            WHERE instancia = %s AND status != 'finalizado'
            ORDER BY data_inicio ASC
        """, (instancia,))
        fila = cur.fetchall()
        
        # Converte datetime para string pro JSON não quebrar
        for item in fila:
            if item.get('data_inicio'):
                item['data_inicio'] = str(item['data_inicio'])
        
        return fila
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
    finally:
        conn.close()

# 2. FINALIZAR ATENDIMENTO (Tira da fila)
@app.delete("/atendimentos/{id}")
def finalizar_atendimento(id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Opção A: Apenas deleta da fila (mais simples)
        cur.execute("DELETE FROM atendimentos WHERE id = %s", (id,))
        
        # Opção B: Se quisesse guardar histórico, faria UPDATE status = 'finalizado'
        # cur.execute("UPDATE atendimentos SET status = 'finalizado' WHERE id = %s", (id,))
        
        conn.commit()
        return {"status": "ok", "msg": "Atendimento encerrado"}
    except Exception as e:
        conn.rollback()
        return JSONResponse(status_code=500, content={"detail": str(e)})
    finally:
        conn.close()