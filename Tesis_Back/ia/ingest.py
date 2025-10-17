import os, io, json, re, hashlib, mimetypes
import boto3
from bs4 import BeautifulSoup
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import JurisDocument, JurisChunk
from .embeddings import embed_texts

from datetime import datetime, date

# ---------------- Fechas robustas ----------------
DATE_RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_RE_DDMMYYYY = re.compile(r"^\d{2}[/-]\d{2}[/-]\d{4}$")

def parse_fecha_safe(raw):
    """
    Devuelve datetime.date o None.
    Acepta: 'YYYY-MM-DD', 'DD/MM/YYYY', 'DD-MM-YYYY'.
    Si está vacío o no se puede, retorna None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    # limpia comillas “ ” y ' "
    s = s.strip('“”"\'')
    if not s or s.lower() in {"n/a", "na", "sin-fecha", "null", "none"}:
        return None

    # ISO (AAAA-MM-DD)
    if DATE_RE_ISO.match(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None

    # dd/mm/aaaa o dd-mm-aaaa
    if DATE_RE_DDMMYYYY.match(s):
        sep = "/" if "/" in s else "-"
        try:
            d, m, y = s.split(sep)
            return date(int(y), int(m), int(d))
        except Exception:
            return None

    # Último intento con dateutil (si está instalado)
    try:
        from dateutil.parser import parse as dtparse
        dt = dtparse(s, dayfirst=True, fuzzy=True)
        return dt.date()
    except Exception:
        return None

# ---------------- S3 / extracción de texto ----------------
BUCKET = "documentos-lexgo-ia-scrapping"

def _s3():
    return boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

def _pdf_text(data: bytes) -> str:
    from pdfminer.high_level import extract_text
    with io.BytesIO(data) as f:
        return extract_text(f)

def extract_text_from_s3(key: str) -> str:
    s3 = _s3()
    obj = s3.get_object(Bucket=BUCKET, Key=key)  # acceso autenticado, sin URL pública
    ct = obj.get("ContentType") or mimetypes.guess_type(key)[0] or ""
    data = obj["Body"].read()

    if "pdf" in (ct or "") or key.lower().endswith(".pdf"):
        from pdfminer.high_level import extract_text
        with io.BytesIO(data) as f:
            return extract_text(f)
    if "html" in (ct or "") or key.lower().endswith(".html"):
        return BeautifulSoup(data, "html.parser").get_text("\n", strip=True)
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return data.decode("latin-1", errors="ignore")

# ---------------- Chunking ----------------
SECTIONS = ["Sumario", "Vistos", "Considerandos", "Fallo", "Parte Dispositiva"]

def split_sections(text: str):
    parts, cur = [], {"section": "Body", "text": ""}
    for line in text.splitlines():
        m = next((s for s in SECTIONS if re.match(rf"^\s*{s}\b", line, re.I)), None)
        if m:
            if cur["text"].strip():
                parts.append(cur)
            cur = {"section": m, "text": line + "\n"}
        else:
            cur["text"] += line + "\n"
    if cur["text"].strip():
        parts.append(cur)
    return parts or [{"section": "Body", "text": text}]

def window_chunks(text: str, max_chars=3500, overlap=400):
    i, n = 0, len(text)
    while i < n:
        j = min(i + max_chars, n)
        yield text[i:j], i, j
        if j >= n:
            break
        i = j - overlap

# ---------------- Ingesta ----------------
@transaction.atomic
def ingest_from_metadata(metadata_key: str):
    s3 = _s3()
    raw = s3.get_object(Bucket=BUCKET, Key=metadata_key)["Body"].read().decode("utf-8")
    meta = json.loads(raw)

    titulo = meta.get("titulo") or "Sin título"
    link = meta.get("link") or meta.get("link_origen") or ""
    fuero = meta.get("fuero", "Laboral")
    jurisd = meta.get("jurisdiccion", "Provincia de Buenos Aires")
    tribunal = meta.get("tribunal")

    fecha_raw = meta.get("fecha")  # podría venir "", “”, dd/mm/aaaa, etc.
    fecha_dt = parse_fecha_safe(fecha_raw)

    # Diagnóstico útil en consola
    print(f"[DEBUG] {metadata_key} -> fecha_raw={repr(fecha_raw)} | fecha_dt={fecha_dt} | tipo={type(fecha_dt)}")

    doc_key = meta.get("s3_key_document") or meta.get("_s3_document_key")

    doc_id = hashlib.sha256(f"{titulo}|{link}".encode("utf-8")).hexdigest()[:32]

    # Arma defaults SIN la clave 'fecha' si es None (evita validadores que transformen el None a cadena)
    defaults = dict(
        titulo=titulo,
        fuero=fuero,
        jurisdiccion=jurisd,
        tribunal=tribunal,
        link_origen=link,
        s3_key_metadata=metadata_key,
        s3_key_document=doc_key,
    )
    if isinstance(fecha_dt, date):
        defaults["fecha"] = fecha_dt
    else:
        # explícitamente no seteamos 'fecha' para que quede NULL si ya existía o None si es nuevo
        pass

    try:
        jd, created = JurisDocument.objects.update_or_create(doc_id=doc_id, defaults=defaults)
    except ValidationError as ve:
        # Si algo externo valida la fecha a string, mostramos y salteamos
        print(f"[SKIP] {metadata_key} -> ValidationError: {ve}")
        return None, 0

    # Extraer texto
    full_text = extract_text_from_s3(doc_key) if doc_key else ""
    if not full_text:
        full_text = meta.get("resumen", "") or titulo

    # Chunks
    chunks = []
    for sec in split_sections(full_text):
        for txt, a, b in window_chunks(sec["text"]):
            if txt.strip():
                chunks.append((sec["section"], txt, a, b))
    if not chunks:
        chunks = [("Body", full_text, 0, len(full_text))]

    # Embeddings (en lote)
    texts = [c[1] for c in chunks]
    embs = embed_texts(texts)

    JurisChunk.objects.filter(doc_id=doc_id).delete()
    objs = []
    for i, ((section, txt, a, b), e) in enumerate(zip(chunks, embs)):
        objs.append(JurisChunk(
            doc_id=doc_id, chunk_id=i, section=section[:64],
            text=txt, span_start=a, span_end=b, embedding=e
        ))
    JurisChunk.objects.bulk_create(objs, batch_size=500)

    return doc_id, len(chunks)
