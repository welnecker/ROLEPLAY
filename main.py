import streamlit as st

# --- imports principais ---
from core.service import gerar_resposta
from core.repositories import get_fact

# --- imports opcionais (com fallbacks para não quebrar o app) ---
try:
    from core.repositories import set_fact, save_interaction
except Exception:
    def set_fact(*_a, **_k):  # no-op
        return None
    def save_interaction(*_a, **_k):  # no-op
        return None

try:
    from core.nsfw import nsfw_enabled
except Exception:
    def nsfw_enabled(_user: str) -> bool:
        return False

try:
    from core.locations import infer_location
except Exception:
    def infer_location(_prompt: str) -> str | None:
        return None

# --- página ---
st.set_page_config(page_title="Roleplay | Mary Massariol", layout="centered")
st.title("Roleplay | Mary Massariol")

# --- estado base ---
st.session_state.setdefault("usuario", "welnecker")
st.session_state.setdefault("modelo", "deepseek/deepseek-chat-v3-0324")
st.session_state.setdefault("history", [])  # [(role, content)]

# --- controles de topo ---
st.text_input("👤 Usuário", key="usuario")
st.selectbox(
    "🧠 Modelo",
    [
        "deepseek/deepseek-chat-v3-0324",
        "anthropic/claude-3.5-haiku",
        "thedrummer/anubis-70b-v1.1",
        "qwen/qwen3-max",
        "nousresearch/hermes-3-llama-3.1-405b",
    ],
    key="modelo",
)

usuario = st.session_state["usuario"]

# --- sidebar (status) ---
nsfw_badge = "✅ Liberado" if nsfw_enabled(usuario) else "🔒 Bloqueado"
st.sidebar.markdown(f"**NSFW:** {nsfw_badge}")
st.sidebar.caption(f"Local atual: {get_fact(usuario, 'local_cena_atual', '—')}")

# --- render histórico já existente ---
for role, content in st.session_state["history"]:
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    else:
        with st.chat_message("assistant", avatar="💚"):
            st.markdown(content)

# --- input do chat ---
if prompt := st.chat_input("Envie sua mensagem para Mary"):
    # mostra e guarda a mensagem do usuário
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state["history"].append(("user", prompt))

    # inferir/fixar local automaticamente (se possível)
    try:
        loc = infer_location(prompt)
        if loc:
            set_fact(usuario, "local_cena_atual", loc)
    except Exception:
        pass

    # gerar resposta
    with st.spinner("Gerando..."):
        try:
            resposta = gerar_resposta(usuario, prompt, model=st.session_state["modelo"])
        except Exception as e:
            resposta = f"Erro ao gerar resposta: {e}"

    # mostrar e guardar a resposta
    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
    st.session_state["history"].append(("assistant", resposta))

    # persistir interação (se disponível)
    try:
        save_interaction(usuario, prompt, resposta, model=st.session_state["modelo"])
    except Exception:
        pass
