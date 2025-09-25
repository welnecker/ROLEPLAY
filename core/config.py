# core/config.py
import os

try:
    import streamlit as st
    _S = getattr(st, "secrets", {})
except Exception:
    _S = {}

def _get(name: str, default: str = "") -> str:
    # 1) st.secrets, 2) env, 3) default
    val = None
    try:
        if hasattr(_S, "get"):
            val = _S.get(name)
    except Exception:
        val = None
    if val is None:
        val = os.getenv(name, default)
    return str(val) if val is not None else default

class _Settings:
    APP_NAME = _get("APP_NAME", "Roleplay")
    APP_PUBLIC_URL = _get("APP_PUBLIC_URL", "https://streamlit.app")

    # Mongo
    MONGO_USER = _get("MONGO_USER", "")
    MONGO_PASS = _get("MONGO_PASS", "")
    MONGO_CLUSTER = _get("MONGO_CLUSTER", "")

    # OpenRouter
    OPENROUTER_TOKEN = _get("OPENROUTER_TOKEN", "")

    # Together
    TOGETHER_API_KEY = _get("TOGETHER_API_KEY", "")
    TOGETHER_BASE_URL = _get("TOGETHER_BASE_URL", "https://api.together.xyz/v1")

settings = _Settings()
