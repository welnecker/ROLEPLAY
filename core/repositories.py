from datetime import datetime
from typing import Any, Dict, List
from .database import get_col
import re

def delete_user_history(usuario: str):
    col = get_col("mary_historia")
    col.delete_many({"usuario": usuario})

def delete_last_interaction(usuario: str):
    col = get_col("mary_historia")
    doc = col.find_one({"usuario": usuario}, sort=[("_id", -1)])
    if doc:
        col.delete_one({"_id": doc["_id"]})

def delete_all_user_data(usuario: str):
    get_col("mary_historia").delete_many({"usuario": usuario})
    get_col("mary_state").delete_many({"usuario": usuario})
    get_col("mary_eventos").delete_many({"usuario": usuario})
    get_col("mary_perfil").delete_many({"usuario": usuario})


def list_interactions(usuario: str, limit: int = 400):
    col = get_col("mary_historia")
    cur = (col.find({"usuario": {"$regex": f"^{re.escape(usuario)}$", "$options": "i"}})
              .sort([("_id", 1)]).limit(limit))
    return list(cur)

def save_interaction(usuario: str, user_msg: str, mary_msg: str, modelo: str = ""):
    get_col("mary_historia").insert_one({
        "usuario": usuario,
        "mensagem_usuario": user_msg,
        "resposta_mary": mary_msg,
        "modelo": modelo,
        "timestamp": datetime.utcnow().isoformat(),
    })

_hist = lambda: get_col("mary_historia")
_state = lambda: get_col("mary_state")
_events = lambda: get_col("mary_eventos")
_profile = lambda: get_col("mary_perfil")

def save_interaction(usuario: str, user_msg: str, mary_msg: str, modelo: str):
    _hist().insert_one({
        "usuario": usuario, "mensagem_usuario": user_msg,
        "resposta_mary": mary_msg, "modelo": modelo,
        "timestamp": datetime.utcnow().isoformat(),
    })

def get_history_docs(usuario: str) -> List[Dict[str, Any]]:
    return list(_hist().find({"usuario": {"$regex": f"^{usuario}$", "$options": "i"}}).sort([("_id", 1)]))

def set_fact(usuario: str, key: str, value: Any, meta: Dict | None = None):
    _state().update_one({"usuario": usuario},
        {"$set": {f"fatos.{key}": value, f"meta.{key}": (meta or {}), "atualizado_em": datetime.utcnow()}},
        upsert=True)

def get_fact(usuario: str, key: str, default=None):
    d = _state().find_one({"usuario": usuario}, {f"fatos.{key}": 1})
    return (d or {}).get("fatos", {}).get(key, default)

def register_event(usuario: str, tipo: str, descricao: str, local: str | None = None, meta: Dict | None = None):
    _events().insert_one({
        "usuario": usuario, "tipo": tipo, "descricao": descricao,
        "local": local, "ts": datetime.utcnow(), "tags": [], "meta": meta or {}
    })

def last_event(usuario: str, tipo: str):
    return _events().find_one({"usuario": usuario, "tipo": tipo}, sort=[("ts", -1)])
