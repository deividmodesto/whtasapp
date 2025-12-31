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

# --- CONFIGURAÇÕES ---
EVO_API_URL = "http://127.0.0.1:8080" # Evolution Local
EVO_API_KEY = "159632"                # Sua Key
DOMAIN_URL = "https://api.modestotech.com.br" # Seu Domínio HTTPS

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
# FUNÇÃO DE ENVIO (CORRIGIDA: TIPO DO BOTÃO + MENU TEXTO)
# ==============================================================================
def enviar_mensagem_smart(instancia, remote_jid, texto_resposta, id_gatilho_atual=None):
    headers = {
        "apikey": EVO_API_KEY,
        "Content-Type": "application/json"
    }
    
    print(f"🤖 Preparando resposta para {remote_jid}...")

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if id_gatilho_atual:
        cur.execute("SELECT * FROM respostas_automacao WHERE id_pai = %s", (id_gatilho_atual,))
    else:
        cur.execute("SELECT * FROM respostas_automacao WHERE id_pai IS NULL AND gatilho != 'default'")
    
    sub_menus = cur.fetchall()
    cur.close()
    conn.close()

    qtd_opcoes = len(sub_menus)
    payload = {}
    endpoint = ""

    # CENÁRIO A: Texto Puro
    if qtd_opcoes == 0:
        endpoint = "sendText"
        payload = {"number": remote_jid, "text": texto_resposta}

    # CENÁRIO B: Botões (Até 3 opções)
    elif qtd_opcoes <= 3:
        endpoint = "sendButtons"
        botoes = []
        for item in sub_menus:
            botoes.append({
                "type": "reply", # <--- AQUI ESTAVA FALTANDO!
                "id": f"btn_{item['id']}", 
                "displayText": item['gatilho']
            })
        
        if id_gatilho_atual and len(botoes) < 3:
             botoes.append({"type": "reply", "id": "btn_home", "displayText": "🏠 Início"})

        payload = {
            "number": remote_jid,
            "text": texto_resposta,
            "buttons": botoes,
            "footer": "Agil Automação"
        }
    
    # CENÁRIO C: Menu Texto (4+ opções) - Blindado contra erros de Lista
    else:
        endpoint = "sendText"
        menu_texto = f"{texto_resposta}\n\n*Escolha uma opção:*\n"
        for i, item in enumerate(sub_menus):
            menu_texto += f"🔹 *{item['gatilho']}*\n"
        
        menu_texto += "\n_(Digite o nome da opção)_"
        
        if id_gatilho_atual:
            menu_texto += "\n\n🏠 Digite *Inicio* para voltar"

        payload = {"number": remote_jid, "text": menu_texto}

    # --- DISPARO ---
    try:
        url_completa = f"{EVO_API_URL}/message/{endpoint}/{instancia}"
        print(f"📡 Enviando via {endpoint}...")
        
        res = requests.post(url_completa, json=payload, headers=headers, timeout=10)
        
        if res.status_code in [200, 201]:
            print(f"✅ SUCESSO! Mensagem enviada.")
        else:
            print(f"❌ ERRO EVOLUTION: {res.status_code} - {res.text}")
            
    except Exception as e:
        print(f"💥 ERRO DE CONEXÃO: {e}")

# ==============================================================================
# ROTA WEBHOOK (COM LÓGICA DE FALLBACK/PEGA-TUDO)
# ==============================================================================
@app.post("/webhook/whatsapp")
async def receber_webhook(request: Request):
    try:
        body = await request.json()
        
        data = body.get("data", {})
        instancia = body.get("instance")
        key = data.get("key", {})
        remote_jid = key.get("remoteJid")
        from_me = key.get("fromMe", False)

        if from_me: return {"status": "ignored_me"} 

        # Descobre o texto
        msg_text = ""
        msg_type = data.get("messageType", "")
        
        if msg_type == "conversation":
            msg_text = data["message"]["conversation"]
        elif msg_type == "extendedTextMessage":
            msg_text = data["message"]["extendedTextMessage"]["text"]
        elif msg_type == "buttonsResponseMessage":
             msg_text = data["message"]["buttonsResponseMessage"]["selectedDisplayText"]
        elif msg_type == "listResponseMessage":
            msg_text = data["message"]["listResponseMessage"]["title"]

        if not msg_text: return {"status": "no_text"}

        print(f"📩 [{instancia}] Mensagem: {msg_text}")
        msg_clean = msg_text.strip()

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Comandos Fixos para chamar o Menu (Case Insensitive)
        if msg_clean.lower() in ["inicio", "início", "menu", "home", "oi", "ola", "olá", "começar"]:
            print(f"🔄 Comando de início detectado: {msg_clean}")
            cur.execute("SELECT * FROM respostas_automacao WHERE gatilho = 'default' AND instancia = %s", (instancia,))
            default = cur.fetchone()
            if default:
                 enviar_mensagem_smart(instancia, remote_jid, default['resposta'], id_gatilho_atual=None)
            else:
                 print("⚠️ ALERTA: O usuário pediu Menu, mas o gatilho 'default' não existe no banco!")
            return {"status": "home"}

        # 2. Busca Gatilho Específico no Banco
        cur.execute("SELECT * FROM respostas_automacao WHERE instancia = %s AND gatilho ILIKE %s", (instancia, msg_clean))
        res = cur.fetchone()
        
        if res:
            # ACHOU UM GATILHO ESPECÍFICO
            enviar_mensagem_smart(instancia, remote_jid, res['resposta'], id_gatilho_atual=res['id'])
            
            # Envia mídia se tiver
            if res['url_midia']:
                 try:
                     extensao = res['url_midia'].split('.')[-1]
                     if len(extensao) > 4: extensao = "jpg"
                 except: extensao = "jpg"
                 
                 mime_type = "image/jpeg"
                 if "png" in extensao.lower(): mime_type = "image/png"
                 elif "mp4" in extensao.lower(): mime_type = "video/mp4"
                 elif "pdf" in extensao.lower(): mime_type = "application/pdf"

                 payload_midia = {
                     "number": remote_jid,
                     "mediatype": res['tipo_midia'] or "image",
                     "mimetype": mime_type,
                     "media": res['url_midia'],
                     "fileName": f"arquivo.{extensao}",
                     "caption": ""
                 }
                 requests.post(f"{EVO_API_URL}/message/sendMedia/{instancia}", json=payload_midia, headers={"apikey": EVO_API_KEY})

        else:
            # 3. NÃO ACHOU NADA? MANDA O MENU PRINCIPAL (DEFAULT)
            print(f"❓ Gatilho '{msg_clean}' não existe. Buscando Default...")
            cur.execute("SELECT * FROM respostas_automacao WHERE gatilho = 'default' AND instancia = %s", (instancia,))
            default = cur.fetchone()
            
            if default:
                 enviar_mensagem_smart(instancia, remote_jid, default['resposta'], id_gatilho_atual=None)
                 print("✅ Enviado menu Default como fallback.")
            else:
                 # Se nem o default existir, o robô fica mudo (para evitar loop infinito de erro)
                 print("⚠️ CRÍTICO: Não existe gatilho 'default' cadastrado para esta instância!")
        
        cur.close()
        conn.close()
        return {"status": "processed"}

    except Exception as e:
        print(f"⚠️ Erro Webhook: {e}")
        return {"status": "error"}
    
# ==============================================================================
# 3. ROTAS DE CADASTRO E LOGIN (NECESSÁRIAS PARA O PAINEL)
# ==============================================================================

@app.post("/salvar")
async def salvar_gatilho(item: Gatilho):
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Upsert: Se existe, atualiza. Se não, cria.
        cur.execute("SELECT id FROM respostas_automacao WHERE instancia=%s AND gatilho=%s", (item.instancia, item.gatilho))
        existe = cur.fetchone()

        if existe:
             cur.execute("""
                UPDATE respostas_automacao SET 
                resposta=%s, tipo_midia=%s, url_midia=%s, id_pai=%s 
                WHERE id=%s
             """, (item.resposta, item.tipo_midia, item.url_midia, item.id_pai, existe[0]))
        else:
            cur.execute("""
                INSERT INTO respostas_automacao 
                (instancia, gatilho, resposta, titulo_menu, categoria, tipo_midia, url_midia, id_pai) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (item.instancia, item.gatilho, item.resposta, item.titulo_menu, item.categoria, item.tipo_midia, item.url_midia, item.id_pai))
        
        conn.commit()
        conn.close()
        return {"status": "sucesso"}
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

# Rotas de Usuário
@app.post("/login")
async def login_usuario(dados: dict):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM usuarios WHERE login = %s AND senha = %s", (dados['login'], dados['senha']))
        user = cur.fetchone()
        conn.close()
        if user: return {"status": "sucesso", "usuario": user}
        raise HTTPException(status_code=401)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/usuarios/cadastrar")
async def cadastrar_usuario(dados: dict):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO usuarios (login, senha, instancia_wa, nome_cliente, plano) VALUES (%s, %s, %s, %s, %s)", (dados['login'], dados['senha'], dados['instancia_wa'], dados['nome_cliente'], dados['plano']))
    conn.commit()
    conn.close()
    return {"status": "sucesso"}

@app.get("/usuarios/listar")
async def listar_usuarios():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, login, instancia_wa, nome_cliente FROM usuarios")
    users = cur.fetchall()
    conn.close()
    return users
    
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