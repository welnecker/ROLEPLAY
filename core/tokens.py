def toklen(txt: str) -> int:
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(txt or ""))
    except Exception:
        return max(1, len((txt or "").split()))
