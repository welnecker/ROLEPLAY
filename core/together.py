# core/together.py
import json, time, requests
from .config import settings

_session = requests.Session()
_session.headers.update({
    "Content-Type": "application/json",
    "Authorization": f"Bearer {settings.TOGETHER_API_KEY}",
})

def chat(payload: dict, timeout: int = 120, retries: int = 0) -> dict:
    """
    Espera payload no formato OpenAI-like:
      { "model": "<slug>", "messages": [...], ... }
    """
    url = f"{settings.TOGETHER_BASE_URL}/chat/completions"
    last = None
    for i in range(retries + 1):
        try:
            r = _session.post(url, data=json.dumps(payload), timeout=timeout)
            if r.ok:
                return r.json()
            raise RuntimeError(f"Together error: {r.text}")
        except Exception as e:
            last = str(e)
        time.sleep(0.5 * (2**i))
    raise RuntimeError(last or "Together unknown error")
