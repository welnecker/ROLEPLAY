import streamlit as st
from core.service import gerar_resposta
from core.repositories import get_fact
from core.nsfw import nsfw_enabled

st.set_page_config(page_title="Roleplay | Mary Massariol", layout="centered")
st.title("Roleplay | Mary Massariol")

st.session_state.setdefault("usuario", "welnecker")
st.session_state.setdefault("modelo", "deepseek/deepseek-chat-v3-0324")

st.text_input("👤 Usuário", key="usuario")
st.selectbox("🧠 Modelo", [
    "deepseek/deepseek-chat-v3-0324",
    "anthropic/claude-3.5-haiku",
    "thedrummer/anubis-70b-v1.1",
    "qwen/qwen3-max",
    "nousresearch/hermes-3-llama-3.1-405b",
], key="modelo")

usuario = st.session_state["usuario"]
st.sidebar.markdown(f"**NSFW:** {'✅ Liberado' if nsfw_enabled(usuario) else '🔒 Bloqueado'}")
st.sidebar.caption(f"Local atual: {get_fact(usuario, 'local_cena_atual', '—')}")

if prompt := st.chat_input("Envie sua mensagem para Mary"):
    with st.chat_message("user"):
        st.markdown(prompt)
    try:
        resposta = gerar_resposta(usuario, prompt, model=st.session_state["modelo"])
    except Exception as e:
        resposta = f"Erro ao gerar resposta: {e}"
    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
