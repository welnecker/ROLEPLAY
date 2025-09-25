# core/together.py
import json, time, requests
from .config import settings

_session = requests.Session()
_session.headers.update({
    "Content-Type": "application/json",
    "X-Title": f"{settings.APP_NAME} | Mary",
})

def chat(payload: dict, timeout: int = 120, retries: int = 2) -> dict:
    """
    Wrapper simples para Together /chat/completions (formato OpenAI-compatible).
    Espera payload com chaves: model, messages, max_tokens, temperature, top_p...
    """
    if not settings.TOGETHER_API_KEY:
        raise RuntimeError("TOGETHER_API_KEY não configurada.")

    url = settings.TOGETHER_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.TOGETHER_API_KEY}"}

    last = None
    for i in range(retries + 1):
        try:
            r = _session.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
            if r.ok:
                return r.json()
            last = r.text
        except Exception as e:
            last = str(e)
        time.sleep(0.75 * (2 ** i))
    raise RuntimeError(f"Together error: {last}")
