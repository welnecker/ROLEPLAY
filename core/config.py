from dataclasses import dataclass
import os
import streamlit as st
def _get(key: str, default: str = "") -> str:
    # tenta st.secrets primeiro; cai para env var
    try:
        import streamlit as st
        v = st.secrets.get(key)
        if v is None:
            return os.getenv(key, default)
        return str(v)
    except Exception:
        return os.getenv(key, default)

@dataclass
class Settings:
    MONGO_USER: str = _get("MONGO_USER", "")
    MONGO_PASS: str = _get("MONGO_PASS", "")
    MONGO_CLUSTER: str = _get("MONGO_CLUSTER", "")
    APP_NAME: str = _get("APP_NAME", "AgnoRoleplay")
    APP_PUBLIC_URL: str = _get("APP_PUBLIC_URL", "https://streamlit.app")
    OPENROUTER_TOKEN: str = _get("OPENROUTER_TOKEN", _get("OPENROUTER_API_KEY", ""))
    TOGETHER_API_KEY: str = _get("TOGETHER_API_KEY", "")  # opcional

settings = Settings()
