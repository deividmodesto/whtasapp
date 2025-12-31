import streamlit as st
import requests
import base64
import time
import pandas as pd 
from io import BytesIO
from PIL import Image
from streamlit_option_menu import option_menu
import graphviz

# =====================================================
# CONFIGURAÇÃO E ESTILO
# =====================================================
st.set_page_config(
    page_title="Agil | Automação Inteligente",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =====================================================
# ESTILO: ESCONDER MARCAS DO STREAMLIT (WHITELABEL)
# =====================================================
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .block-container {
                padding-top: 1rem;
                padding-bottom: 0rem;
            }
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

st.markdown("""
    <style>
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.05);
        text-align: center;
    }
    .metric-label { font-size: 14px; color: #888; margin-bottom: 5px; }
    .metric-value { font-size: 28px; font-weight: bold; color: #333; }
    .status-ok { color: #28a745; font-weight: bold; }
    .status-err { color: #dc3545; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# Configurações de API
API_URL = "http://127.0.0.1:8000"
EVO_URL = "http://127.0.0.1:8080"
EVO_API_KEY = "159632"

HEADERS_EVO = {
    "apikey": EVO_API_KEY,
    "Content-Type": "application/json"
}

# =====================================================
# FUNÇÃO DE LOGIN
# =====================================================
def login_sistema():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        c1, c2, c3 = st.columns([1, 2, 1])
        
        with c2:
            try:
                img_logo = Image.open("logo.png")
                col_img_esq, col_img_centro, col_img_dir = st.columns([1, 5, 1])
                with col_img_centro:
                      st.image(img_logo, width=350)
            except:
                st.markdown("<h1 style='text-align: center;'>🚀 Agil </h1>", unsafe_allow_html=True)
            
            st.markdown("<h5 style='text-align: center; color: gray; margin-top: -10px;'>Automação Inteligente para o seu negócio</h5>", unsafe_allow_html=True)
            st.write("") 

            with st.container(border=True):
                with st.form("login_form", clear_on_submit=False):
                    user_input = st.text_input("👤 Usuário", placeholder="Seu login")
                    pass_input = st.text_input("🔑 Senha", type="password", placeholder="••••••")
                    
                    st.write("")
                    submit = st.form_submit_button("Acessar Sistema", type="primary", use_container_width=True)

                    if submit:
                        if not user_input or not pass_input:
                             st.warning("Preencha todos os campos.")
                        else:
                            payload = {"login": user_input, "senha": pass_input}
                            res = None
                            
                            with st.spinner("Conectando..."):
                                try:
                                    res = requests.post(f"{API_URL}/login", json=payload, timeout=5)
                                except:
                                    time.sleep(0.5) 
                                    try:
                                        res = requests.post(f"{API_URL}/login", json=payload, timeout=10)
                                    except:
                                        st.error("❌ Erro de conexão. Verifique se a API está online.")
                                        return False

                            if res and res.status_code == 200:
                                st.session_state.user_info = res.json()["usuario"]
                                st.session_state.autenticado = True
                                st.toast("Bem-vindo de volta!", icon="🚀")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error("Usuário ou senha incorretos.")
            
            st.markdown("<p style='text-align: center; font-size: 12px; color: #ccc; margin-top: 30px;'>© 2025 Agil Tecnologia.</p>", unsafe_allow_html=True)
                        
        return False
    
    return True

def verificar_status_whatsapp(instancia):
    try:
        res = requests.get(f"{EVO_URL}/instance/connectionState/{instancia}", headers=HEADERS_EVO, timeout=3)
        if res.status_code == 200:
            estado = res.json().get("instance", {}).get("state", "unknown")
            return estado == "open"
        return False
    except:
        return False

# =====================================================
# FUNÇÃO AUXILIAR WEBHOOK
# =====================================================
def ativar_webhook(nome_instancia):
    url_destino = "http://127.0.0.1:8000/webhook/whatsapp"

    payload = {
        "webhook": {
            "enabled": True,
            "url": url_destino,
            "byEvents": False,
            "base64": False,
            "events": ["MESSAGES_UPSERT", "MESSAGES_UPDATE", "SEND_MESSAGE"]
        }
    }

    try:
        res = requests.post(f"{EVO_URL}/webhook/set/{nome_instancia}", json=payload, headers=HEADERS_EVO, timeout=10)
        
        if res.status_code in [200, 201]:
            return True, "Webhook ativado com sucesso! 🚀"
        else:
            return False, f"Erro Evolution ({res.status_code}): {res.text}"

    except Exception as e:
        return False, f"Erro de Conexão: {str(e)}"

if not login_sistema():
    st.stop()

user_info = st.session_state.user_info
instancia_selecionada = user_info["instancia_wa"]
login_usuario = user_info["login"]

# =====================================================
# SIDEBAR
# =====================================================
with st.sidebar:
    st.title("Painel de Controle")
    st.write(f"Bem-vindo, **{user_info['nome_cliente']}**")
    
    if verificar_status_whatsapp(instancia_selecionada):
        st.markdown("Status: <span class='status-ok'>Online 🟢</span>", unsafe_allow_html=True)
    else:
        st.markdown("Status: <span class='status-err'>Offline 🔴</span>", unsafe_allow_html=True)
        
    st.divider()
    if st.button("Sair", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

# =====================================================
# MENU PRINCIPAL (CORRIGIDO: MENU PRINCIPAL ADICIONADO)
# =====================================================
opcoes = ["Dashboard", "Meus Gatilhos", "Menu Principal", "Mapa Mental", "Simulador", "Conexão"]
icones = ["speedometer2", "lightning-charge", "house", "diagram-3", "chat-dots", "qr-code"]

if login_usuario == "admin":
    opcoes.append("Gestão de Clientes")
    icones.append("people")

selected = option_menu(None, opcoes, icons=icones, orientation="horizontal", 
    styles={"container": {"padding": "0!important", "background-color": "#fafafa"}})

# =====================================================
# ABA 1: DASHBOARD
# =====================================================
if selected == "Dashboard":
    st.subheader("📊 Visão Geral")
    
    try:
        res = requests.get(f"{API_URL}/listar/{instancia_selecionada}")
        gatilhos = res.json() if res.status_code == 200 else []
        qtd_gatilhos = len(gatilhos)
        status_bool = verificar_status_whatsapp(instancia_selecionada)
        status_texto = "Conectado" if status_bool else "Desconectado"
        cor_status = "green" if status_bool else "red"
    except:
        qtd_gatilhos = 0
        status_texto = "Erro API"
        cor_status = "orange"

    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Status do WhatsApp</div>
            <div class="metric-value" style="color: {cor_status}">{status_texto}</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Gatilhos Ativos</div>
            <div class="metric-value">{qtd_gatilhos}</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Plano Atual</div>
            <div class="metric-value">Pro</div>
        </div>
        """, unsafe_allow_html=True)

    st.write("---")
    st.info("💡 **Dica:** Configure sua mensagem de boas-vindas na aba 'Menu Principal'.")

# =====================================================
# ABA 2: MEUS GATILHOS
# =====================================================
elif selected == "Meus Gatilhos":
    st.subheader("⚡ Gerenciar Respostas Automáticas")
    
    c1, c2 = st.columns([1, 2])
    
    # Formulário
    with c1:
        with st.container(border=True):
            st.markdown("##### ➕ Novo Gatilho")
            
            # Busca pais
            opcoes_pais = {'Nenhum (Menu Principal)': None}
            try:
                r_pais = requests.get(f"{API_URL}/listar/{instancia_selecionada}")
                if r_pais.status_code == 200:
                    for p in r_pais.json():
                        # Só mostra como opção de pai quem NÃO TEM pai (nível 1)
                        if p['id_pai'] is None and p['gatilho'] != 'default':
                            opcoes_pais[f"{p['gatilho']}"] = p['id']
            except:
                pass
            
            escolha_pai = st.selectbox("Este gatilho pertence a qual menu?", list(opcoes_pais.keys()))
            id_pai_selecionado = opcoes_pais[escolha_pai]

            novo_gatilho = st.text_input("Gatilho (O que o cliente digita)", placeholder="Ex: 1 ou Cardapio")
            nova_resposta = st.text_area("Resposta do Robô", height=100)
            arquivo_enviado = st.file_uploader("Anexar Mídia (Opcional)", type=["png", "jpg", "jpeg", "pdf", "mp4"])
            
            tipo_msg = "texto"
            url_final = None

            if st.button("💾 Salvar Gatilho", use_container_width=True):
                if novo_gatilho and nova_resposta:
                    
                    if arquivo_enviado:
                        with st.spinner("Enviando arquivo..."):
                            files = {"file": (arquivo_enviado.name, arquivo_enviado, arquivo_enviado.type)}
                            try:
                                res_up = requests.post(f"{API_URL}/upload", files=files)
                                if res_up.status_code == 200:
                                    url_final = res_up.json()["url"]
                                    if arquivo_enviado.type.startswith("image"): tipo_msg = "image"
                                    elif arquivo_enviado.type.startswith("video"): tipo_msg = "video"
                                    elif "pdf" in arquivo_enviado.type: tipo_msg = "document"
                            except Exception as e:
                                st.error(f"Erro upload: {e}")
                                st.stop()

                    payload = {
                        "instancia": instancia_selecionada, 
                        "gatilho": novo_gatilho, 
                        "resposta": nova_resposta,
                        "tipo_midia": tipo_msg,
                        "url_midia": url_final,
                        "id_pai": id_pai_selecionado
                    }
                    requests.post(f"{API_URL}/salvar", json=payload)
                    st.success("Salvo!")
                    time.sleep(1)
                    st.rerun()

    # Tabela Hierárquica
    with c2:
        st.markdown("### 🗂️ Seus Menus")
        res = requests.get(f"{API_URL}/listar/{instancia_selecionada}")
        
        if res.status_code == 200:
            dados = res.json()
            if dados:
                # Remove o 'default' da lista visual para não confundir (ele fica na aba Menu Principal)
                dados_visuais = dados
                
                pais = [d for d in dados_visuais if d['id_pai'] is None]
                filhos = [d for d in dados_visuais if d['id_pai'] is not None]

                for pai in pais:
                    with st.expander(f"📂 **{pai['gatilho']}**"):
                        st.write(f"📝 {pai['resposta']}")
                        if st.button("🗑️ Excluir Menu", key=f"del_pai_{pai['id']}"):
                            requests.delete(f"{API_URL}/excluir/{pai['id']}")
                            st.rerun()

                        meus_filhos = [f for f in filhos if f['id_pai'] == pai['id']]
                        if meus_filhos:
                            st.markdown("---")
                            for filho in meus_filhos:
                                with st.container():
                                    c_f1, c_f2 = st.columns([4, 1])
                                    c_f1.info(f"🔹 **{filho['gatilho']}**: {filho['resposta']}")
                                    if c_f2.button("❌", key=f"del_filho_{filho['id']}"):
                                        requests.delete(f"{API_URL}/excluir/{filho['id']}")
                                        st.rerun()
                        else:
                            st.caption("Sem sub-opções.")
            else:
                st.info("Nenhum gatilho cadastrado.")

# =====================================================
# ABA 3: MENU PRINCIPAL (RESTABELECIDA!)
# =====================================================
elif selected == "Menu Principal":
    st.subheader("🏠 Configurar Menu Inicial")
    st.info("Esta mensagem será enviada quando o cliente disser 'Oi', 'Menu' ou algo que o robô não entenda.")
    
    # Tenta buscar se já existe um default
    texto_atual = ""
    try:
        res = requests.get(f"{API_URL}/listar/{instancia_selecionada}")
        if res.status_code == 200:
            for item in res.json():
                if item['gatilho'] == 'default':
                    texto_atual = item['resposta']
                    break
    except:
        pass

    with st.container(border=True):
        st.markdown("**Mensagem de Boas-Vindas / Menu:**")
        novo_texto = st.text_area("Digite o menu aqui:", value=texto_atual, height=200, placeholder="Ex: Olá! Sou o assistente virtual. Digite 1 para Cardápio, 2 para Horários...")
        
        if st.button("💾 Atualizar Menu Principal", type="primary"):
            payload = {
                "instancia": instancia_selecionada, 
                "gatilho": "default", # O segredo: gatilho se chama 'default'
                "resposta": novo_texto,
                "id_pai": None
            }
            requests.post(f"{API_URL}/salvar", json=payload)
            st.success("Menu Principal atualizado com sucesso!")
            time.sleep(1)
            st.rerun()

# =====================================================
# ABA 4: MAPA MENTAL
# =====================================================
elif selected == "Mapa Mental":
    st.subheader("🧠 Mapa Neural do Robô")
    try:
        res = requests.get(f"{API_URL}/listar/{instancia_selecionada}")
        gatilhos = res.json() if res.status_code == 200 else []

        if not gatilhos:
            st.warning("Cadastre gatilhos para gerar o mapa.")
        else:
            graph = graphviz.Digraph()
            graph.attr(bgcolor='transparent', rankdir='LR')
            graph.attr('node', shape='box', style='rounded,filled', fontname='Helvetica', color='white')
            graph.attr('edge', color='#888888')

            graph.node('CLIENTE', label='📱 Início', fillcolor='#25D366', fontcolor='white', shape='circle')
            ids_existentes = {g['id'] for g in gatilhos}

            for item in gatilhos:
                if item['gatilho'] == 'default':
                     # Nó especial para o Menu Principal
                     graph.node(f"G_{item['id']}", label="🏠 Menu Principal", fillcolor='#FFBD45', fontcolor='black')
                     graph.edge('CLIENTE', f"G_{item['id']}", label="Oi/Erro")
                else:
                    id_pai = item['id_pai']
                    texto = item['gatilho']
                    cor_fundo = '#AED581' if id_pai else '#E0E0E0'
                    
                    graph.node(f"G_{item['id']}", label=f"Opção:\n'{texto}'", fillcolor=cor_fundo, fontcolor='black')

                    if id_pai is None:
                        # Se não tem pai e não é default, é um gatilho solto (atalho)
                        graph.edge('CLIENTE', f"G_{item['id']}", style="dashed", label="Atalho")
                    elif id_pai in ids_existentes:
                        graph.edge(f"G_{id_pai}", f"G_{item['id']}")

            st.graphviz_chart(graph, use_container_width=True)

    except Exception as e:
        st.error(f"Erro ao gerar mapa: {e}")

# =====================================================
# ABA 5: SIMULADOR
# =====================================================
elif selected == "Simulador":
    st.subheader("💬 Teste seu Robô")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Digite algo..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        res = requests.get(f"{API_URL}/listar/{instancia_selecionada}")
        resposta_robo = "..."
        
        if res.status_code == 200:
            gatilhos = res.json()
            encontrou = False
            
            # Busca exata
            for g in gatilhos:
                if g['gatilho'].lower() in prompt.lower() and g['gatilho'] != 'default':
                    resposta_robo = g['resposta']
                    encontrou = True
                    break
            
            # Busca Default
            if not encontrou:
                for g in gatilhos:
                    if g['gatilho'] == 'default':
                        resposta_robo = g['resposta']
                        break
        
        time.sleep(0.5)
        st.session_state.chat_history.append({"role": "assistant", "content": resposta_robo})
        with st.chat_message("assistant"):
            st.markdown(resposta_robo)

# =====================================================
# ABA 6: CONEXÃO
# =====================================================
elif selected == "Conexão":
    st.subheader("📱 Conexão com WhatsApp")
    
    status_texto = "..."
    try:
        r_check = requests.get(f"{EVO_URL}/instance/connectionState/{instancia_selecionada}", headers=HEADERS_EVO, timeout=2)
        if r_check.status_code == 200:
            state = r_check.json().get('instance', {}).get('state', 'close')
            if state == 'open':
                st.success(f"Status: ONLINE ({state})")
            else:
                st.warning(f"Status: DESCONECTADO ({state})")
        else:
            st.error("Status: Erro na API")
    except:
        st.error("Status: API Offline ou Bloqueada")

    st.divider()
    
    col_qr, col_sts = st.columns(2)
    
    with col_qr:
        if st.button("🔄 Gerar QR Code", use_container_width=True):
            with st.spinner("Solicitando QR Code..."):
                try:
                    res = requests.get(f"{EVO_URL}/instance/connect/{instancia_selecionada}", headers=HEADERS_EVO, timeout=10)
                    if res.status_code == 200:
                        data = res.json()
                        if "base64" in data:
                            img = Image.open(BytesIO(base64.b64decode(data["base64"].split(",")[1])))
                            st.image(img, caption="Leia no seu WhatsApp")
                        elif "qrcode" in data:
                            st.code(data["qrcode"])
                        else:
                            st.warning("Já conectado.")
                    else:
                        st.error(f"Erro QR Code: {res.status_code}")
                except Exception as e:
                    st.error(f"Falha de conexão: {e}")
    
    with col_sts:
        st.info("Diagnóstico")
        if st.button("🔌 Forçar Reativação do Webhook"):
            try:
                with st.spinner("Configurando..."):
                    sucesso, mensagem = ativar_webhook(instancia_selecionada)
                    if sucesso:
                        st.success(mensagem)
                        st.balloons()
                    else:
                        st.error(f"❌ Falha: {mensagem}")            
            except Exception as e:
                st.error(f"Erro ao conectar: {e}")

        if st.button("📊 Ver JSON Status"):
            try:
                res = requests.get(f"{EVO_URL}/instance/connectionState/{instancia_selecionada}", headers=HEADERS_EVO, timeout=5)
                st.json(res.json())
            except:
                st.error("Erro ao buscar JSON")

# =====================================================
# ABA ADMIN: GESTÃO DE CLIENTES
# =====================================================
elif selected == "Gestão de Clientes":
    st.subheader("👥 Gestão Administrativa")
    aba_cad, aba_list = st.tabs(["➕ Novo Cliente", "📋 Listagem"])

    with aba_cad:
        with st.container(border=True):
            col1, col2 = st.columns(2)
            nome = col1.text_input("Nome", placeholder="João Silva")
            login = col1.text_input("Login", placeholder="joao123")
            senha = col2.text_input("Senha", type="password")
            instancia = col2.text_input("Instância", help="Sem espaços")

            if st.button("🚀 Criar Cliente"):
                if nome and login and instancia:
                    payload_db = {"nome_cliente": nome, "login": login, "senha": senha, "instancia_wa": instancia, "plano": "Mensal"}
                    try:
                        res_db = requests.post(f"{API_URL}/usuarios/cadastrar", json=payload_db)
                        if res_db.status_code == 200:
                            res_evo = requests.post(f"{EVO_URL}/instance/create", json={"instanceName": instancia}, headers=HEADERS_EVO)
                            if res_evo.status_code in [200, 201]:
                                with st.spinner("Configurando Webhook..."):
                                    time.sleep(3)
                                    ativar_webhook(instancia)
                                    st.success("Cliente criado com sucesso!")
                            else:
                                st.error(f"Erro Evolution: {res_evo.text}")
                        else:
                            st.error(f"Erro Banco: {res_db.text}")
                    except Exception as e:
                        st.error(f"Erro: {e}")

    with aba_list:
        try:
            res = requests.get(f"{API_URL}/usuarios/listar")
            if res.status_code == 200:
                usuarios = res.json()
                for user in usuarios:
                    with st.container(border=True):
                        c1, c2 = st.columns([4, 1])
                        c1.markdown(f"**{user['nome_cliente']}** ({user['login']}) - Instância: `{user['instancia_wa']}`")
                        if c2.button("Excluir", key=f"del_adm_{user['id']}"):
                            requests.delete(f"{API_URL}/usuarios/excluir/{user['id']}")
                            requests.delete(f"{EVO_URL}/instance/delete/{user['instancia_wa']}", headers=HEADERS_EVO)
                            st.rerun()
            else:
                st.error("Erro ao listar.")
        except:
            st.error("Erro conexão.")