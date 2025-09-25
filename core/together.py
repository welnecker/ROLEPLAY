# core/together.py
import json, time, requests
from .config import settings

_BASE = getattr(settings, "TOGETHER_BASE_URL", "https://api.together.xyz").rstrip("/")
_PATH = getattr(settings, "TOGETHER_CHAT_PATH", "/v1/chat/completions")
_URL  = f"{_BASE}{_PATH}"

_session = requests.Session()
_session.headers.update({
    "Content-Type": "application/json",
    "Authorization": f"Bearer {getattr(settings, 'TOGETHER_API_KEY', '')}",
})

def chat(payload: dict, timeout: int = 120, retries: int = 2) -> dict:
    last = None
    for i in range(retries + 1):
        try:
            r = _session.post(_URL, data=json.dumps(payload), timeout=timeout)
            if r.ok:
                return r.json()
            last = r.text
        except Exception as e:
            last = str(e)
        time.sleep(0.75 * (2 ** i))
    raise RuntimeError(f"Together error: {last}")
