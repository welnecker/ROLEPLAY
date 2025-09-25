from dataclasses import dataclass
import os
import streamlit as st
from pydantic import BaseSettings

def _get(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.getenv(key, default))  # type: ignore[attr-defined]
    except Exception:
        return os.getenv(key, default)

@dataclass(frozen=True)
class Settings(BaseSettings):
    APP_NAME: str = "Roleplay"
    APP_PUBLIC_URL: str = "https://streamlit.app"

    # Mongo / OpenRouter já existentes...
    MONGO_USER: str = os.getenv("MONGO_USER", "")
    MONGO_PASS: str = os.getenv("MONGO_PASS", "")
    MONGO_CLUSTER: str = os.getenv("MONGO_CLUSTER", "")
    OPENROUTER_TOKEN: str = os.getenv("OPENROUTER_TOKEN", "")

    # ✅ Together
    TOGETHER_API_KEY: str = os.getenv("TOGETHER_API_KEY", "")
    TOGETHER_BASE_URL: str = os.getenv("TOGETHER_BASE_URL", "https://api.together.xyz/v1")

settings = Settings()
