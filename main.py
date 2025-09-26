# main.py
from typing import Optional, List, Tuple
import streamlit as st

# --- imports principais ---
try:
    from core.service import gerar_resposta
except Exception as e:
    st.error(f"Falha ao importar core.service: {e}")
    raise

# Repositório
try:
    from core.repositories import (
        get_fact, get_facts, get_history_docs, set_fact,
        delete_user_history, delete_last_interaction, delete_all_user_data, reset_nsfw,
        register_event, list_events
    )
except Exception as e:
    st.error(f"Falha ao importar core.repositories: {e}")
    raise

# NSFW (opcional)
try:
    from core.nsfw import nsfw_enabled
except Exception:
    def nsfw_enabled(_user: str) -> bool:
        return False

# Inferência de local
try:
    from core.locations import infer_from_prompt as infer_location
except Exception:
    def infer_location(_prompt: str) -> Optional[str]:
        return None


# --- helpers ---
def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _reload_history(user_key: str):
    """Recarrega histórico do Mongo para o user_key (ordem cronológica asc)."""
    st.session_state["history"] = []
    try:
        docs = get_history_docs(user_key)
        for d in docs:
            u = (d.get("mensagem_usuario") or "").strip()
            a = (d.get("resposta_mary") or "").strip()
            if u:
                st.session_state["history"].append(("user", u))
            if a:
                st.session_state["history"].append(("assistant", a))
    except Exception as e:
        st.sidebar.warning(f"Não foi possível carregar o histórico: {e}")
    st.session_state["history_loaded_for"] = user_key


# --- página ---
st.set_page_config(page_title="Roleplay | Mary Massariol", layout="centered")
st.title("Roleplay | Mary Massariol")

# --- estado base ---
st.session_state.setdefault("usuario", "welnecker")
st.session_state.setdefault("modelo", "deepseek/deepseek-chat-v3-0324")
st.session_state.setdefault("personagem", "Mary")
st.session_state.setdefault("history", [])               # type: List[Tuple[str, str]]
st.session_state.setdefault("history_loaded_for", None)
st.session_state.setdefault("auto_loc", True)

# --- controles topo ---
c1, c2 = st.columns([2, 2])
with c1:
    st.text_input("👤 Usuário", key="usuario")
with c2:
    st.selectbox("🎭 Personagem", ["Mary", "Laura"], key="personagem")

MODEL_OPTIONS = [
    # OpenRouter
    "deepseek/deepseek-chat-v3-0324",
    "anthropic/claude-3.5-haiku",
    "thedrummer/anubis-70b-v1.1",
    "qwen/qwen3-max",
    "nousresearch/hermes-3-llama-3.1-405b",
    # Together
    "together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
    "together/deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
    "together/google/gemma-2-27b-it",
]
st.selectbox("🧠 Modelo", MODEL_OPTIONS, key="modelo")

usuario = st.session_state["usuario"]
personagem = st.session_state["personagem"]  # "Mary" ou "Laura"
modelo = st.session_state["modelo"]

# chave por personagem (Mary usa legado; outras isolam)
usuario_key = usuario if personagem == "Mary" else f"{usuario}::{personagem.lower()}"

# --- carregar histórico por personagem ---
if st.session_state["history_loaded_for"] != usuario_key:
    _reload_history(usuario_key)

# --- sidebar: STATUS ---
try:
    local_atual = get_fact(usuario_key, "local_cena_atual", "—")
except Exception:
    local_atual = "—"

nsfw_badge = "✅ Liberado" if nsfw_enabled(usuario_key) else "🔒 Bloqueado"
provider = "Together" if modelo.startswith("together/") else "OpenRouter"

st.sidebar.markdown(f"**NSFW:** {nsfw_badge}")
st.sidebar.caption(f"Local atual: {local_atual}")
st.sidebar.caption(f"Personagem: **{personagem}**")
st.sidebar.caption(f"Provedor: **{provider}**")

st.sidebar.markdown("---")
st.session_state["auto_loc"] = st.sidebar.checkbox(
    "📍 Inferir local automaticamente",
    value=st.session_state["auto_loc"]
)

# --- sidebar: MEMÓRIA CANÔNICA (ver/adicionar) ---
st.sidebar.subheader("🧠 Memória Canônica")

# listar fatos
try:
    fatos = get_facts(usuario_key)
except Exception:
    fatos = {}
if fatos:
    for k, v in fatos.items():
        st.sidebar.write(f"- `{k}` → {v}")
else:
    st.sidebar.caption("_Nenhum fato salvo._")

# listar últimos eventos
st.sidebar.markdown("**Eventos (últimos 5)**")
try:
    evs = list_events(usuario_key, limit=5)
except Exception:
    evs = []
if evs:
    for ev in evs:
        ts = ev.get("ts")
        ts_str = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts or "")
        st.sidebar.write(
            f"- **{ev.get('tipo','?')}** — {ev.get('descricao','?')} "
            f"({ev.get('local') or '—'}) em {ts_str}"
        )
else:
    st.sidebar.caption("_Nenhum evento recente._")

# forms para salvar fato/evento
with st.sidebar.form("form_fato", clear_on_submit=True):
    st.markdown("**Adicionar Fato**")
    f_chave = st.text_input("Chave", placeholder="ex.: parceiro_atual")
    f_valor = st.text_input("Valor", placeholder="ex.: Janio")
    salvar_fato = st.form_submit_button("💾 Salvar fato")
    if salvar_fato and f_chave.strip():
        try:
            set_fact(usuario_key, f_chave.strip(), f_valor.strip(), {"fonte": "manual"})
            st.success("Fato salvo.")
            _rerun()
        except Exception as e:
            st.error(f"Falha ao salvar fato: {e}")

with st.sidebar.form("form_evento", clear_on_submit=True):
    st.markdown("**Adicionar Evento**")
    e_tipo = st.text_input("Tipo", placeholder="ex.: primeiro_encontro")
    e_desc = st.text_area("Descrição", placeholder="texto curto factual", height=60)
    e_local = st.text_input("Local (opcional)", placeholder="ex.: Padaria do Bairro")
    salvar_evento = st.form_submit_button("💾 Salvar evento")
    if salvar_evento and e_tipo.strip() and e_desc.strip():
        try:
            register_event(
                usuario_key,
                e_tipo.strip(),
                e_desc.strip(),
                (e_local.strip() or None),
                {"fonte": "manual"},
            )
            st.success("Evento salvo.")
            _rerun()
        except Exception as e:
            st.error(f"Falha ao salvar evento: {e}")

# --- sidebar: manutenção ---
st.sidebar.markdown("---")
st.sidebar.subheader("🧹 Manutenção")

colA, colB = st.sidebar.columns(2)
if colA.button("🔄 Resetar histórico"):
    try:
        delete_user_history(usuario_key)
        st.session_state["history"] = []
        st.session_state["history_loaded_for"] = None
        st.sidebar.success("Histórico apagado.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao resetar histórico: {e}")

if colB.button("⏪ Apagar último turno"):
    try:
        ok = delete_last_interaction(usuario_key)
        if ok:
            _reload_history(usuario_key)
            st.sidebar.info("Último turno apagado.")
            _rerun()
        else:
            st.sidebar.warning("Não havia interações para apagar.")
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar último turno: {e}")

if st.sidebar.button("🧨 Apagar TUDO (chat + memórias)"):
    try:
        delete_all_user_data(usuario_key)
        st.session_state["history"] = []
        st.session_state["history_loaded_for"] = None
        st.sidebar.success("Tudo apagado para este personagem/usuário.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar tudo: {e}")

# Atalhos NSFW ON/OFF por personagem
if st.sidebar.button("🔓 Marcar primeira vez (NSFW ON)"):
    try:
        set_fact(usuario_key, "virgem", False, {"fonte": "sidebar"})
        register_event(
            usuario_key,
            "primeira_vez",
            f"{personagem} teve sua primeira vez.",
            "motel status",
            {"origin": "sidebar"},
        )
        st.sidebar.success("NSFW liberado e evento registrado.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao marcar primeira vez: {e}")

if st.sidebar.button("🔒 Forçar NSFW OFF"):
    try:
        reset_nsfw(usuario_key)
        st.sidebar.success("NSFW desativado para este personagem/usuário.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao forçar NSFW OFF: {e}")

# --- render histórico ---
for role, content in st.session_state["history"]:
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    else:
        with st.chat_message("assistant", avatar="💚"):
            st.markdown(content)

# --- input do chat ---
if prompt := st.chat_input(f"Envie sua mensagem para {personagem}"):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state["history"].append(("user", prompt))

    if st.session_state["auto_loc"]:
        try:
            loc = infer_location(prompt)
            if loc:
                set_fact(usuario_key, "local_cena_atual", loc, {"fonte": "ui/auto"})
        except Exception:
            pass

    with st.spinner("Gerando..."):
        try:
            # Passamos o usuário base e a personagem separadamente;
            # o service cuida do namespace de memória/histórico.
            resposta = gerar_resposta(usuario, prompt, model=modelo, character=personagem)
        except Exception as e:
            resposta = f"Erro ao gerar resposta: {e}"

    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
    st.session_state["history"].append(("assistant", resposta))
