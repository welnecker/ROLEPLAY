import json, time, requests
from .config import settings

_session = requests.Session()
_session.headers.update({
    "Content-Type": "application/json",
    "HTTP-Referer": settings.APP_PUBLIC_URL,
    "X-Title": f"{settings.APP_NAME} | Mary",
})

def chat(payload: dict, timeout: int = 120, retries: int = 2) -> dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_TOKEN}"}
    last = None
    for i in range(retries + 1):
        try:
            r = _session.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
            if r.ok: return r.json()
            last = r.text
        except Exception as e:
            last = str(e)
        time.sleep(0.75 * (2**i))
    raise RuntimeError(f"OpenRouter error: {last}")

