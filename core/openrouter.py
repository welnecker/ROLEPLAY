# core/openrouter.py
import json, time, requests
from .config import settings

_session = requests.Session()
_session.headers.update({
    "Content-Type": "application/json",
    "HTTP-Referer": settings.APP_PUBLIC_URL,
    "X-Title": f"{settings.APP_NAME} | Mary",
    "Authorization": f"Bearer {settings.OPENROUTER_TOKEN}",
})

def chat(payload: dict, timeout: int = 120, retries: int = 0) -> dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    last = None
    for i in range(retries + 1):
        try:
            r = _session.post(url, data=json.dumps(payload), timeout=timeout)
            if r.ok:
                return r.json()
            raise RuntimeError(f"OpenRouter error: {r.text}")
        except Exception as e:
            last = str(e)
        time.sleep(0.5 * (2**i))
    raise RuntimeError(last or "OpenRouter unknown error")

