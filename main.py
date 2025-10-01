# main.py
from typing import Optional, List, Tuple
import time, hmac, hashlib        # << aqui, junto dos imports
import streamlit as st

# ============ BLOQUEIO POR SENHA (GATE) ============
def _check_scrypt(pwd: str) -> bool:
    cfg = st.secrets.get("auth", {})
    salt_hex = cfg.get("salt", "")
    hash_hex = cfg.get("password_scrypt", "")
    if not salt_hex or not hash_hex:
        return False
    try:
        calc = hashlib.scrypt(
            pwd.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=2**14, r=8, p=1
        ).hex()
        return hmac.compare_digest(calc, hash_hex)
    except Exception:
        return False

def require_password(app_name: str = "App protegido"):
    # anti-bruteforce simples
    st.session_state.setdefault("_auth_ok", False)
    st.session_state.setdefault("_auth_attempts", 0)
    st.session_state.setdefault("_auth_block_until", 0.0)

    now = time.time()
    if now < st.session_state["_auth_block_until"]:
        wait = int(st.session_state["_auth_block_until"] - now)
        st.error(f"Tentativas excessivas. Tente novamente em {wait}s.")
        st.stop()

    if st.session_state["_auth_ok"]:
        with st.sidebar:
            if st.button("Sair"):
                for k in ["_auth_ok", "_auth_attempts", "_auth_block_until"]:
                    st.session_state.pop(k, None)
                st.rerun()
        return  # autenticado → deixa o app continuar

    # Tela de login
    st.title(f"🔒 {app_name}")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if _check_scrypt(pwd):
            st.session_state["_auth_ok"] = True
            st.session_state["_auth_attempts"] = 0
            st.success("Acesso liberado.")
            st.rerun()
        else:
            st.session_state["_auth_attempts"] += 1
            backoff = 5 * (3 ** max(0, st.session_state["_auth_attempts"] - 1))  # 5s,15s,45s…
            st.session_state["_auth_block_until"] = time.time() + backoff
            st.error("Senha incorreta.")
            st.stop()

    # ponto-chave: se não autenticou, parar TUDO
    st.stop()
# ==== FIM DO GATE ====# ===================================================

# --- imports principais do app ---
try:
    from core.service import gerar_resposta
except Exception as e:
    st.error(f"Falha ao importar core.service: {e}")
    raise

# ---------- página ----------
st.set_page_config(page_title="Roleplay | Mary Massariol", layout="centered")
require_password("Roleplay | Mary Massariol")   # <<< BLOQUEIO AQUI
st.title("Roleplay | Mary Massariol")

# ---------- Repositório (com fallbacks que NÃO quebram a UI) ----------
def _noop(*_a, **_k):
    return None

def _return_empty_list(*_a, **_k):
    return []

try:
    from core.repositories import (
        get_fact, get_facts, get_history_docs, set_fact,
        delete_user_history, delete_last_interaction, delete_all_user_data, reset_nsfw,
        register_event, list_events,
    )
except Exception:
    # Fallbacks para manter a aplicação utilizável mesmo sem todas as funções
    def get_fact(_u: str, _k: str, default=None): return default
    def get_facts(_u: str): return {}
    def get_history_docs(_u: str, limit: int = 400): return []
    set_fact = _noop
    delete_user_history = lambda _u: 0
    delete_last_interaction = lambda _u: False
    def delete_all_user_data(_u: str): return {"hist": 0, "state": 0, "eventos": 0, "perfil": 0}
    reset_nsfw = _noop
    register_event = _noop
    list_events = _return_empty_list

# ---------- NSFW (opcional) ----------
try:
    from core.nsfw import nsfw_enabled
except Exception:
    def nsfw_enabled(_user: str) -> bool:
        return False

# ---------- Inferência de local ----------
try:
    from core.locations import infer_from_prompt as infer_location
except Exception:
    def infer_location(_prompt: str) -> Optional[str]:
        return None

# ---------- helpers ----------
def _rerun():
    if hasattr(st, "rerun"): st.rerun()
    else: st.experimental_rerun()

def _reload_history(user_key: str):
    st.session_state["history"] = []
    try:
        docs = get_history_docs(user_key)
        for d in docs:
            u = (d.get("mensagem_usuario") or "").strip()
            a = (d.get("resposta_mary") or "").strip()
            if u: st.session_state["history"].append(("user", u))
            if a: st.session_state["history"].append(("assistant", a))
    except Exception as e:
        st.sidebar.warning(f"Não foi possível carregar o histórico: {e}")
    st.session_state["history_loaded_for"] = user_key

# ---------- página ----------
st.set_page_config(page_title="Roleplay | Mary Massariol", layout="centered")
st.title("Roleplay | Mary Massariol")

# ---------- estado base (interno) ----------
st.session_state.setdefault("usuario", "Janio Donisete")
st.session_state.setdefault("modelo", "deepseek/deepseek-chat-v3-0324")
st.session_state.setdefault("personagem", "Mary")
st.session_state.setdefault("history", [])               # type: List[Tuple[str, str]]
st.session_state.setdefault("history_loaded_for", None)
st.session_state.setdefault("auto_loc", True)

# ---------- estado dos WIDGETS (ui_*) ----------
st.session_state.setdefault("ui_usuario", st.session_state["usuario"])
st.session_state.setdefault("ui_personagem", st.session_state["personagem"])
st.session_state.setdefault("ui_modelo", st.session_state["modelo"])
st.session_state.setdefault("ui_auto_loc", st.session_state["auto_loc"])

# ---------- controles topo (usar chaves únicas ui_*) ----------
c1, c2 = st.columns([2,2])
with c1:
    st.text_input("👤 Usuário", key="ui_usuario")
with c2:
    st.selectbox("🎭 Personagem", ["Mary", "Laura", "Narith"], key="ui_personagem")

MODEL_OPTIONS = [
    # OpenRouter
    "deepseek/deepseek-chat-v3-0324",
    "anthropic/claude-3.5-haiku",
    "thedrummer/anubis-70b-v1.1",
    "qwen/qwen3-max",
    "nousresearch/hermes-3-llama-3.1-405b",
    # Together
    "together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
    "together/Qwen/Qwen2.5-72B-Instruct",
    "together/google/gemma-2-27b-it",
]
st.selectbox("🧠 Modelo", MODEL_OPTIONS, key="ui_modelo")

# ---------- sincroniza UI -> estado interno ----------
st.session_state["usuario"]    = st.session_state["ui_usuario"]
st.session_state["personagem"] = st.session_state["ui_personagem"]
st.session_state["modelo"]     = st.session_state["ui_modelo"]

usuario    = st.session_state["usuario"]
personagem = st.session_state["personagem"]  # "Mary" | "Laura" | "Narith"
modelo     = st.session_state["modelo"]

# chave de usuário por personagem (Mary usa legado; outras isolam)
usuario_key = usuario if personagem == "Mary" else f"{usuario}::{personagem.lower()}"

# ---------- carregar histórico por personagem ----------
if st.session_state["history_loaded_for"] != usuario_key:
    _reload_history(usuario_key)

# ---------- sidebar: STATUS ----------
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
st.session_state["ui_auto_loc"] = st.sidebar.checkbox(
    "📍 Inferir local automaticamente",
    value=st.session_state["ui_auto_loc"],
    help="Quando ligado, tenta detectar o lugar a partir da sua mensagem e fixa em memória."
)
# sync
st.session_state["auto_loc"] = st.session_state["ui_auto_loc"]

# ---------- sidebar: FLERTE (permitir quase-traição) ----------
if personagem == "Laura":
    flirt_fact_val = bool(get_fact(usuario_key, "flirt_mode", False))
    st.session_state.setdefault("ui_flirt_mode", flirt_fact_val)
    st.session_state["ui_flirt_mode"] = st.sidebar.checkbox(
        "💃 Flerte (permitir quase-traição)",
        value=st.session_state["ui_flirt_mode"],
        help="Ligado: permite flerte com terceiro até quase acontecer; antes do sexo ela interrompe. Desligado: barra cedo."
    )
    if st.session_state["ui_flirt_mode"] != flirt_fact_val:
        try:
            set_fact(usuario_key, "flirt_mode", bool(st.session_state["ui_flirt_mode"]), {"fonte": "sidebar"})
        except Exception as e:
            st.sidebar.warning(f"Falha ao salvar preferência de flerte: {e}")
else:
    # Esconde/neutraliza para Mary/Narith (sem alterar fato salvo da Laura em outra key)
    st.sidebar.caption("💃 Flerte: disponível apenas para **Laura**.")

# ---------- sidebar: MEMÓRIA CANÔNICA (ver/adicionar) ----------
st.sidebar.markdown("---")
st.sidebar.subheader("🧠 Memória Canônica")

# listar fatos
try:
    fatos = get_facts(usuario_key) or {}
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
    evs = list_events(usuario_key, limit=5) or []
except Exception:
    evs = []
if evs:
    for ev in evs:
        ts = ev.get("ts")
        ts_str = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts or "")
        st.sidebar.write(f"- **{ev.get('tipo','?')}** — {ev.get('descricao','?')} ({ev.get('local') or '—'}) em {ts_str}")
else:
    st.sidebar.caption("_Nenhum evento recente._")

# forms para salvar fato/evento (com keys únicos)
with st.sidebar.form("form_fato", clear_on_submit=True):
    st.markdown("**Adicionar Fato**")
    f_chave = st.text_input("Chave", placeholder="ex.: parceiro_atual", key="fato_chave")
    f_valor = st.text_input("Valor", placeholder="ex.: Janio", key="fato_valor")
    salvar_fato = st.form_submit_button("💾 Salvar fato")
    if salvar_fato and (f_chave or "").strip():
        try:
            set_fact(usuario_key, f_chave.strip(), (f_valor or "").strip(), {"fonte": "manual"})
            st.success("Fato salvo.")
            _rerun()
        except Exception as e:
            st.error(f"Falha ao salvar fato: {e}")

with st.sidebar.form("form_evento", clear_on_submit=True):
    st.markdown("**Adicionar Evento**")
    e_tipo  = st.text_input("Tipo", placeholder="ex.: primeiro_encontro", key="evento_tipo")
    e_desc  = st.text_area("Descrição", placeholder="texto curto factual", height=60, key="evento_desc")
    e_local = st.text_input("Local (opcional)", placeholder="ex.: Padaria do Zé", key="evento_local")
    salvar_evento = st.form_submit_button("💾 Salvar evento")
    if salvar_evento and (e_tipo or "").strip() and (e_desc or "").strip():
        try:
            register_event(usuario_key, e_tipo.strip(), e_desc.strip(), ((e_local or "").strip() or None), {"fonte": "manual"})
            st.success("Evento salvo.")
            _rerun()
        except Exception as e:
            st.error(f"Falha ao salvar evento: {e}")

# ---------- sidebar: manutenção ----------
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

# Atalho NSFW ON/OFF por personagem
if st.sidebar.button("🔓 Marcar primeira vez (NSFW ON)"):
    try:
        set_fact(usuario_key, "virgem", False, {"fonte": "sidebar"})
        register_event(usuario_key, "primeira_vez", f"{personagem} teve sua primeira vez.", "motel status", {"origin": "sidebar"})
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

# ---------- render histórico ----------
for role, content in st.session_state["history"]:
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    else:
        with st.chat_message("assistant", avatar="💚"):
            st.markdown(content)

# ---------- CONTINUAR (botão) + input do chat ----------
st.write("")  # espaçamento antes do rodapé
continuar_clicked = st.button(
    "▶️ Continuar",
    key="btn_continuar",
    help="Seguir a cena a partir da última resposta, mantendo o mesmo local e personagens."
)

user_prompt = st.chat_input(f"Envie sua mensagem para {personagem}")

# Resolve a intenção final desta iteração
prompt: Optional[str] = None
is_auto_continue = False

if continuar_clicked and not user_prompt:
    # Prompt especial para continuação lógica (sem mudar local)
    prompt = (
        "CONTINUAR: Prossiga a cena exatamente de onde a última resposta parou. "
        "Mantenha LOCAL_ATUAL, personagens presentes e tom. Não resuma; avance a ação e o diálogo em 1ª pessoa."
    )
    is_auto_continue = True
elif user_prompt:
    prompt = user_prompt

# ---------- ciclo de geração ----------
if prompt:
    # mostra e guarda a mensagem do usuário (ou “Continuar”)
    with st.chat_message("user"):
        st.markdown("🔁 **Continuar**" if is_auto_continue else prompt)
    st.session_state["history"].append(("user", "🔁 Continuar" if is_auto_continue else prompt))

    # Inferir/fixar local APENAS quando veio texto do usuário (não no Continuar)
    if (not is_auto_continue) and st.session_state["auto_loc"]:
        try:
            loc = infer_location(prompt)
            if loc:
                set_fact(usuario_key, "local_cena_atual", loc, {"fonte": "ui/auto"})
        except Exception:
            pass

    # gerar resposta
    with st.spinner("Gerando..."):
        try:
            resposta = gerar_resposta(usuario, prompt, model=modelo, character=personagem)
        except Exception as e:
            resposta = f"Erro ao gerar resposta: {e}"

    # mostrar e guardar a resposta
    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
    st.session_state["history"].append(("assistant", resposta))
