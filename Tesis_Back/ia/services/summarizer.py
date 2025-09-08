# ia/services/summarizer.py (parche)
import logging
from typing import Dict
from django.conf import settings
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

log = logging.getLogger(__name__)

SYSTEM_GUIDE = (
    "Sos un asistente jurídico: resumí con precisión sin inventar hechos. "
    "Si falta evidencia, indicalo. Estructura sugerida: "
    "TL;DR (viñetas), Hechos, Cuestiones jurídicas, Decisión (si aplica), "
    "Argumentos, Dudas/ambigüedades."
)

_tokenizer = _model = None

def _ensure_local():
    """
    Fuerza tokenizer 'slow' para evitar dependencia en tiktoken.
    Requiere 'sentencepiece' instalado (ya lo tenés en requirements).
    """
    global _tokenizer, _model
    if _tokenizer is None or _model is None:
        model_id = getattr(settings, "FALLBACK_MODEL_ID", "google/mt5-base")
        log.info(f"[summarizer] Cargando modelo local (slow tokenizer): {model_id}")
        # 👇 clave: use_fast=False
        _tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False)
        _model = AutoModelForSeq2SeqLM.from_pretrained(model_id)

def summarize(text: str, max_words: int = 300, style: str = "legal-brief") -> Dict[str, str]:
    _ensure_local()
    MAX_INPUT_CHARS = getattr(settings, "NLP_MAX_AGGREGATED_CHARS", 30000)
    prompt = (
        f"{SYSTEM_GUIDE}\n\n"
        f"Resumir en español en {max_words} palabras (estilo {style}):\n{text[:MAX_INPUT_CHARS]}"
    )
    inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
    ids = _model.generate(
        **inputs,
        max_new_tokens=280,
        num_beams=4,
        length_penalty=1.0,
        early_stopping=True,
        no_repeat_ngram_size=3,
    )
    out = _tokenizer.decode(ids[0], skip_special_tokens=True)
    return {"summary": out, "engine": "local"}


def summarize(text: str, max_words: int = 300, style: str = "legal-brief") -> Dict[str, str]:
    _ensure_local()
    MAX_INPUT_CHARS = getattr(settings, "NLP_MAX_AGGREGATED_CHARS", 30000)
    prompt = (
        f"{SYSTEM_GUIDE}\n\n"
        f"Resumir en español en {max_words} palabras (estilo {style}):\n{text[:MAX_INPUT_CHARS]}"
    )
    inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
    ids = _model.generate(
        **inputs,
        max_new_tokens=280,
        num_beams=4,
        length_penalty=1.0,
        early_stopping=True,
        no_repeat_ngram_size=3,
    )
    out = _tokenizer.decode(ids[0], skip_special_tokens=True)
    return {"summary": out, "engine": "local"}
