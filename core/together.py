# core/together.py
import json, time, requests
from .config import settings

class ProviderError(RuntimeError):
    ...

_session = requests.Session()
_session.headers.update({
    "Content-Type": "application/json",
    "HTTP-Referer": settings.APP_PUBLIC_URL,
    "X-Title": f"{settings.APP_NAME} | Mary",
    "Authorization": f"Bearer {settings.TOGETHER_API_KEY}",
})

def chat(payload: dict, timeout: int = 120, retries: int = 1) -> dict:
    """
    Chama a Together e LEVANTA ProviderError em QUALQUER não-200.
    Sem fallback silencioso.
    """
    url = f"{settings.TOGETHER_BASE_URL}/chat/completions"
    last_err = None
    for i in range(retries + 1):
        try:
            r = _session.post(url, data=json.dumps(payload), timeout=timeout)
            if r.ok:
                return r.json()
            # tenta extrair erro estruturado
            try:
                j = r.json()
                msg = j.get("error", {}).get("message") or r.text
            except Exception:
                msg = r.text
            last_err = f"Together error [{r.status_code}] model={payload.get('model')}: {msg}"
        except Exception as e:
            last_err = f"Together request failed: {e}"
        time.sleep(0.75 * (2 ** i))
    raise ProviderError(last_err or "Together unknown error")
