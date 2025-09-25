from urllib.parse import quote_plus
from pymongo import MongoClient
from .config import settings

_client = None

def get_client() -> MongoClient:
    global _client
    if _client is None:
        uri = (
            f"mongodb+srv://{settings.MONGO_USER}:{quote_plus(settings.MONGO_PASS)}"
            f"@{settings.MONGO_CLUSTER}/?retryWrites=true&w=majority&appName={settings.APP_NAME}"
        )
        _client = MongoClient(uri)
    return _client

def get_db():
    return get_client().get_database(settings.APP_NAME)

def get_col(name: str):
    return get_db().get_collection(name)
