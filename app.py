import streamlit as st
import requests
import base64
import time
from io import BytesIO
from PIL import Image
from streamlit_option_menu import option_menu

# =====================================================
# CONFIGURAÇÃO E ESTILO
# =====================================================
st.set_page_config(page_title="Gestor SaaS - Fluxos WhatsApp", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; }
    .stExpander { border: 1px solid #ddd; border-radius: 8px; background-color: white; }
    </style>
    """, unsafe_allow_html=True)

# Configurações de API
API_URL = "http://127.0.0.1:8000"
EVO_URL = "http://168.119.255.226:8080"
EVO_API_KEY = "159632"
WEBHOOK_N8N = "http://127.0.0.1:5678/webhook/whatsapp"

HEADERS_EVO = {
    "apikey": EVO_API_KEY,
    "Content-Type": "application/json"
}

# =====================================================
# SISTEMA DE LOGIN
# =====================================================
def login_sistema():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        cols = st.columns([1, 2, 1])
        with cols[1]:
            st.title("🚀 Portal SaaS")
            with st.container(border=True):
                user_input = st.text_input("Usuário")
                pass_input = st.text_input("Senha", type="password")
                if st.button("Acessar Painel"):
                    try:
                        # Testando a conexão antes de enviar
                        res = requests.post(f"{API_URL}/login", json={"login": user_input, "senha": pass_input}, timeout=5)
                        
                        if res.status_code == 200:
                            st.session_state.user_info = res.json()["usuario"]
                            st.session_state.autenticado = True
                            st.rerun()
                        else:
                            st.error(f"Credenciais inválidas. (Status: {res.status_code})")
                    except requests.exceptions.ConnectionError:
                        st.error(f"❌ Não foi possível conectar na API em {API_URL}. O servidor Uvicorn está rodando?")
                    except Exception as e:
                        st.error(f"💥 Erro inesperado: {e}")
        return False
    return True

if not login_sistema():
    st.stop()

# Dados do usuário logado
user_info = st.session_state.user_info
instancia_selecionada = user_info["instancia_wa"]
login_usuario = user_info["login"]

# =====================================================
# SIDEBAR ORGANIZADA
# =====================================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/5968/5968841.png", width=70)
    st.title(f"Olá, {user_info['nome_cliente']}")
    st.info(f"📍 Instância: {instancia_selecionada}")
    st.divider()
    if st.button("Deslogar"):
        st.session_state.autenticado = False
        st.rerun()

# =====================================================
# MENU SUPERIOR
# =====================================================
opcoes = ["Visualizar Fluxo", "Cadastrar Gatilho", "Configurar Menu", "Conectar WhatsApp"]
icones = ["diagram-3", "plus-circle", "house", "whatsapp"]

if login_usuario == "admin":
    opcoes.append("Gestão de Clientes")
    icones.append("people")

selected = option_menu(None, opcoes, icons=icones, orientation="horizontal", 
    styles={"container": {"padding": "0!important", "background-color": "#fafafa"}})

# =====================================================
# FUNÇÃO AUXILIAR WEBHOOK
# =====================================================
def ativar_webhook(nome_instancia):
    settings_payload = {
        "webhook": {
            "enabled": True,
            "url": WEBHOOK_N8N,
            "byEvents": False,
            "base64": False,
            "events": ["MESSAGES_UPSERT"]
        }
    }
    
    # Lista de rotas possíveis para a v2.3.7 (Tentaremos todas até uma funcionar)
    rotas = [
        f"{EVO_URL}/settings/update/{nome_instancia}",
        f"{EVO_URL}/instance/setSettings/{nome_instancia}",
        f"{EVO_URL}/webhook/set/{nome_instancia}"
    ]
    
    for rota in rotas:
        try:
            res = requests.post(rota, json=settings_payload, headers=HEADERS_EVO, timeout=5)
            if res.status_code in [200, 201]:
                return True
        except:
            continue
            
    # Se todas falharem, vamos mostrar o erro da última tentativa para diagnosticar
    try:
        ultimo_res = requests.post(rotas[0], json=settings_payload, headers=HEADERS_EVO)
        st.error(f"Erro detalhado Evolution: {ultimo_res.status_code} - {ultimo_res.text}")
    except Exception as e:
        st.error(f"Erro de conexão física: {e}")
        
    return False
# =====================================================
# ABA: VISUALIZAR FLUXO
# =====================================================
if selected == "Visualizar Fluxo":
    st.subheader(f"📊 Seus Gatilhos Ativos")
    try:
        res = requests.get(f"{API_URL}/listar/{instancia_selecionada}")
        if res.status_code == 200:
            dados = res.json()
            if dados:
                for item in dados:
                    with st.expander(f"🔹 Gatilho: **{item['gatilho']}**"):
                        st.write(f"**Resposta:** {item['resposta']}")
                        if st.button("Remover", key=f"del_{item['id']}"):
                            requests.delete(f"{API_URL}/excluir/{item['id']}")
                            st.rerun()
            else:
                st.info("Nenhum gatilho configurado.")
    except:
        st.error("Erro ao buscar dados.")

# =====================================================
# ABA: CADASTRAR GATILHO
# =====================================================
elif selected == "Cadastrar Gatilho":
    st.subheader("📝 Criar Automação")
    with st.container(border=True):
        gatilho = st.text_input("Se o cliente escrever (ex: 'Preço'):")
        resposta = st.text_area("O robô responderá:", height=150)
        if st.button("Salvar Automação"):
            if gatilho and resposta:
                payload = {"instancia": instancia_selecionada, "gatilho": gatilho, "resposta": resposta}
                requests.post(f"{API_URL}/salvar", json=payload)
                st.success("Salvo com sucesso!")
            else:
                st.warning("Preencha todos os campos.")

# =====================================================
# ABA: CONFIGURAR MENU
# =====================================================
elif selected == "Configurar Menu":
    st.subheader("👋 Menu de Boas-Vindas")
    texto = st.text_area("Mensagem padrão enviada para novos contatos:", value="Olá! Como posso te ajudar hoje?", height=150)
    if st.button("Atualizar Mensagem Principal"):
        payload = {"instancia": instancia_selecionada, "gatilho": "default", "resposta": texto}
        requests.post(f"{API_URL}/salvar", json=payload)
        st.success("Menu atualizado!")

# =====================================================
# ABA: CONECTAR WHATSAPP (BOTÃO REATIVAR WEBHOOK AQUI)
# =====================================================
elif selected == "Conectar WhatsApp":
    st.subheader("🔗 Conexão e Status")
    c1, c2, c3 = st.columns(3)
    
    with c1:
        if st.button("🔄 Gerar QR Code"):
            res = requests.get(f"{EVO_URL}/instance/connect/{instancia_selecionada}", headers=HEADERS_EVO)
            if res.status_code == 200:
                data = res.json()
                if "base64" in data:
                    img = Image.open(BytesIO(base64.b64decode(data["base64"].split(",")[1])))
                    st.image(img, width=250, caption="Escaneie para conectar")
                else:
                    st.info("Instância já está conectada.")
    
    with c2:
        if st.button("📊 Verificar Status"):
            res = requests.get(f"{EVO_URL}/instance/connectionState/{instancia_selecionada}", headers=HEADERS_EVO)
            st.json(res.json())

    with c3:
        st.markdown("⚠️ **Problemas na resposta?**")
        if st.button("🔌 Reativar Webhook", help="Força a conexão entre WhatsApp e o n8n"):
            if ativar_webhook(instancia_selecionada):
                st.success("Webhook reativado com sucesso!")
            else:
                st.error("Falha ao reativar Webhook.")

# =====================================================
# ABA: GESTÃO DE CLIENTES (ADMIN) - VERSÃO UNIFICADA 
# =====================================================
elif selected == "Gestão de Clientes":
    st.subheader("👥 Gestão Administrativa de Clientes")
    aba_cad, aba_list = st.tabs(["➕ Novo Cliente", "📋 Listagem de Clientes"])

    # --- SUB-ABA: CADASTRAR ---
    with aba_cad:
        with st.container(border=True):
            col1, col2 = st.columns(2)
            nome = col1.text_input("Nome do Cliente", placeholder="Ex: João Silva")
            login = col1.text_input("Login (Username)", placeholder="Ex: joao123")
            senha = col2.text_input("Senha", type="password")
            instancia = col2.text_input("Nome da Instância", help="Sem espaços ou caracteres especiais")

            if st.button("🚀 Criar Cliente e Instância"):
                if nome and login and instancia:
                    # 1. SALVAR NO BANCO DE DADOS (FastAPI)
                    payload_db = {
                        "nome_cliente": nome, 
                        "login": login, 
                        "senha": senha, 
                        "instancia_wa": instancia, 
                        "plano": "Mensal"
                    }
                    
                    try:
                        res_db = requests.post(f"{API_URL}/usuarios/cadastrar", json=payload_db)
                        
                        if res_db.status_code == 200:
                            # 2. CRIAR INSTÂNCIA NA EVOLUTION API
                            # Na v2.3.7 enviamos o mínimo no create
                            res_evo = requests.post(
                                f"{EVO_URL}/instance/create",
                                json={"instanceName": instancia},
                                headers=HEADERS_EVO
                            )

                            if res_evo.status_code in [200, 201]:
                                with st.spinner("Instância criada! Configurando Webhook v2..."):
                                    time.sleep(3) # Tempo vital para a v2.3.7 processar a nova instância
                                
                                # 3. ATIVAR WEBHOOK (Usando a estrutura correta para v2.3.7)
                                if ativar_webhook(instancia):
                                    st.success(f"✅ Sucesso! Cliente {nome} criado e Webhook configurado.")
                                    st.balloons()
                                else:
                                    st.warning("⚠️ Cliente criado, mas o Webhook falhou. Ative manualmente na aba 'Conectar WhatsApp'.")
                            else:
                                st.error(f"❌ Erro ao criar na Evolution: {res_evo.text}")
                        else:
                            st.error(f"❌ Erro ao salvar no Banco: {res_db.text}")
                    except Exception as e:
                        st.error(f"💥 Erro de conexão: {e}")
                else:
                    st.error("Preencha todos os campos obrigatórios.")

    # --- SUB-ABA: LISTAR E EXCLUIR ---
    with aba_list:
        try:
            res = requests.get(f"{API_URL}/usuarios/listar")
            if res.status_code == 200:
                usuarios = res.json()
                if usuarios:
                    for user in usuarios:
                        with st.container(border=True):
                            c1, c2 = st.columns([4, 1])
                            c1.markdown(f"**Cliente:** {user['nome_cliente']} | **Login:** `{user['login']}`")
                            c1.write(f"Instância: `{user['instancia_wa']}`")
                            
                            # Botão de Excluir (Banco + Evolution)
                            if c2.button("Excluir", key=f"del_adm_{user['id']}"):
                                with st.spinner("Removendo dados..."):
                                    # Remove do seu Banco
                                    requests.delete(f"{API_URL}/usuarios/excluir/{user['id']}")
                                    # Remove da Evolution
                                    requests.delete(f"{EVO_URL}/instance/delete/{user['instancia_wa']}", headers=HEADERS_EVO)
                                    st.success("Removido com sucesso!")
                                    st.rerun()
                else:
                    st.info("Nenhum cliente cadastrado no momento.")
            else:
                st.error("Falha ao carregar lista de usuários da API.")
        except Exception as e:
            st.error(f"Erro ao listar clientes: {e}")