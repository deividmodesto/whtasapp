import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
import psycopg2.extras # Necessário para o RealDictCursor
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware

# --- FORÇA O PYTHON A IGNORAR O WINDOWS ---
os.environ["PYTHONIOENCODING"] = "utf-8"

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Configurações do Banco
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

# --- MODELOS DE DADOS ---
class Gatilho(BaseModel):
    instancia: str
    gatilho: str
    resposta: str
    titulo_menu: Optional[str] = "Geral"
    categoria: Optional[str] = "Atendimento"

# --- ROTAS DE GATILHOS (ROBÔ) ---

@app.post("/salvar")
async def salvar_gatilho(item: Gatilho):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO respostas_automacao (instancia, gatilho, resposta, titulo_menu, categoria) 
               VALUES (%s, %s, %s, %s, %s)""",
            (item.instancia, item.gatilho, item.resposta, item.titulo_menu, item.categoria)
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "sucesso"}
    except Exception as e:
        print(f"Erro ao salvar: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/listar/{instancia}")
async def listar_gatilhos(instancia: str):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, gatilho, resposta FROM respostas_automacao WHERE instancia = %s", (instancia,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        return []

@app.delete("/excluir/{id}")
async def excluir_gatilho(id: int):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM respostas_automacao WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROTAS DE USUÁRIOS E LOGIN ---

@app.post("/login")
async def login_usuario(dados: dict):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = "SELECT * FROM usuarios WHERE login = %s AND senha = %s AND ativo = TRUE"
        cur.execute(query, (dados['login'], dados['senha']))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if user:
            return {"status": "sucesso", "usuario": user}
        else:
            raise HTTPException(status_code=401, detail="Invalido")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/usuarios/cadastrar")
async def cadastrar_usuario(dados: dict):
    try:
        conn = get_connection()
        cur = conn.cursor()
        query = """INSERT INTO usuarios (login, senha, instancia_wa, nome_cliente, plano) 
                   VALUES (%s, %s, %s, %s, %s)"""
        cur.execute(query, (dados['login'], dados['senha'], dados['instancia_wa'], dados['nome_cliente'], dados['plano']))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/usuarios/listar")
async def listar_usuarios():
    try:
        conn = get_connection()
        # O RealDictCursor é fundamental para o Streamlit entender os dados
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) 
        cur.execute("SELECT id, login, instancia_wa, nome_cliente, ativo FROM usuarios")
        users = cur.fetchall()
        cur.close()
        conn.close()
        return users
    except Exception as e:
        print(f"Erro ao listar usuários: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.delete("/usuarios/excluir/{id}")
async def excluir_usuario(id: int):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))