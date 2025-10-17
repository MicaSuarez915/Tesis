# ia/embeddings.py
import os
from functools import lru_cache
from openai import OpenAI

DEFAULT_EMBED_MODEL = "text-embedding-3-small"  # 1536 dims

@lru_cache(maxsize=1)
def _client():
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _as_list(texts):
    if isinstance(texts, (list, tuple)):
        return list(texts)
    return [texts]

def embed_texts(texts, model: str = DEFAULT_EMBED_MODEL):
    """
    Devuelve una lista de vectores (uno por texto).
    Compatible con openai>=1.x/2.x
    """
    client = _client()
    items = _as_list(texts)
    # Lotes por si tenés muchos textos
    BATCH = int(os.getenv("EMBED_BATCH", "64"))
    out = []
    for i in range(0, len(items), BATCH):
        chunk = items[i:i+BATCH]
        resp = client.embeddings.create(model=model, input=chunk)
        out.extend([d.embedding for d in resp.data])
    return out

def embed_query(q: str, model: str = DEFAULT_EMBED_MODEL):
    return embed_texts([q], model=model)[0]
