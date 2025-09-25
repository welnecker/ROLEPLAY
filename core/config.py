from dataclasses import dataclass
import os
import streamlit as st

def _get(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.getenv(key, default))  # type: ignore[attr-defined]
    except Exception:
        return os.getenv(key, default)

@dataclass(frozen=True)
class Settings:
    APP_NAME: str = _get("APP_NAME", "AgnoRoleplay")
    APP_PUBLIC_URL: str = _get("APP_PUBLIC_URL", "https://streamlit.app")
    MONGO_USER: str = _get("MONGO_USER", "")
    MONGO_PASS: str = _get("MONGO_PASS", "")
    MONGO_CLUSTER: str = _get("MONGO_CLUSTER", "")
    OPENROUTER_TOKEN: str = _get("OPENROUTER_TOKEN") or _get("OPENROUTER_API_KEY", "")

settings = Settings()
