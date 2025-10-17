from typing import List, Dict, Any, Optional
from django.db import connection
from .embeddings import embed_query

import re
from typing import Optional

def clean_urls_in_text(text: str) -> str:
    """
    Elimina cualquier texto residual (saltos de línea, 'nSi', 'Si', espacios, etc.)
    que quede pegado después de una URL.
    """
    if not text:
        return text

    # Patrón: captura la URL y corta todo lo que venga justo después (saltos, nSi, Si, espacios)
    pattern = re.compile(
        r"(https?://[^\s)>\]]+)"      # URL válida
        r"(?:\\n+|\s+)*(?:n?Si)?",    # Basura pegada (saltos o texto suelto)
        re.IGNORECASE
    )

    cleaned = pattern.sub(r"\1", text)  # deja solo la URL limpia

    # Limpia saltos de línea excesivos cerca de las URLs
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def _to_vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.10f}" for x in v) + "]"



# --------- BÚSQUEDA ESTRICTA (FTS obligatorio + filtros + umbral cosine) ----------
def _mk_websearch_query(user_q: str, required_terms: Optional[list[str]] = None) -> str:
    qs = user_q.strip()
    if required_terms:
        req = " ".join([f"+\"{t}\"" for t in required_terms if t])
        qs = (qs + " " + req).strip()
    return qs

def search_chunks_strict(
    query: str,
    k: int = 8,
    fuero: Optional[str] = "Laboral",
    jurisdiccion: Optional[str] = None,  
    tribunal: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    min_chars: int = 200,
    min_score: float = 0.80,
    max_per_doc: int = 2,
    debug: bool = False,
) -> Dict[str, Any]:
    emb = embed_query(query)
    emb_lit = _to_vector_literal(emb)

    # Forzamos algunos términos comunes en laboral PBA (opcional)
    required = []
    ql = query.lower()
    if "art" in ql and "80" in ql:
        required.append("80")
    if "la plata" in ql:
        required.append("La Plata")
    if "certific" in ql:
        required.append("certificado")
    web_q = _mk_websearch_query(query, required_terms=required)

    where: list[str] = ["length(jc.text) >= %s"]
    params: list = [int(min_chars)]

    if fuero:
        where.append("LOWER(jd.fuero) = LOWER(%s)")
        params.append(fuero)

    if jurisdiccion:
        where.append("jd.jurisdiccion ILIKE %s")
        params.append(f"%{jurisdiccion}%")

    if tribunal:
        where.append("jd.tribunal ILIKE %s")
        params.append(f"%{tribunal}%")

    where.append("to_tsvector('spanish', coalesce(jd.titulo,'') || ' ' || jc.text) @@ websearch_to_tsquery('spanish', %s)")
    params.append(web_q)

    sql = f"""
    SELECT
      jc.doc_id, jc.chunk_id, jc.section, jc.text,
      1 - (jc.embedding <=> %s::vector) AS score,
      jd.titulo, jd.tribunal, jd.fecha, jd.link_origen, jd.s3_key_document
    FROM ia_jurischunk jc
    JOIN ia_jurisdocument jd ON jd.doc_id = jc.doc_id
    WHERE {" AND ".join(where)}
    ORDER BY jc.embedding <=> %s::vector
    LIMIT %s;
    """
    params_final = [emb_lit] + params + [emb_lit, int(k * 8)]  # pedimos extra

    with connection.cursor() as cur:
        cur.execute(sql, params_final)
        rows = cur.fetchall()

    hits: List[Dict[str, Any]] = []
    per_doc = {}
    for r in rows:
        score = float(r[4])
        if score < min_score:
            continue
        doc_id = r[0]
        if per_doc.get(doc_id, 0) >= max_per_doc:
            continue
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        doc_url = r[8]
        text_clean = clean_urls_in_text(r[3] or "")
        hits.append({
            "doc_id": doc_id,
            "chunk_id": r[1],
            "section": r[2],
            "text": text_clean,
            "score": score,
            "titulo": r[5],
            "tribunal": r[6],
            "fecha": r[7].isoformat() if r[7] else None,
            "link_origen": doc_url,
            "s3_key_document": r[9],
        })
        if len(hits) >= k:
            break

    if debug:
        return {
            "hits": hits,
            "debug": {
                "where": where,
                "min_score": min_score,
                "got_rows": len(rows),
                "kept_hits": len(hits),
            }
        }
    return {"hits": hits}

# --------- BÚSQUEDA FLEXIBLE (vector only + filtros suaves) ----------
def search_chunks(
    query: str,
    k: int = 8,
    fuero: Optional[str] = None,
    jurisdiccion: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    min_chars: int = 80,
) -> List[Dict[str, Any]]:
    emb = embed_query(query)
    emb_lit = _to_vector_literal(emb)

    where: list[str] = ["length(jc.text) >= %s"]
    params: list = [int(min_chars)]

    if fuero:
        where.append("LOWER(jd.fuero) = LOWER(%s)")
        params.append(fuero)
    if jurisdiccion:
        where.append("jd.jurisdiccion ILIKE %s")
        params.append(f"%{jurisdiccion}%")
    if desde:
        where.append("jd.fecha IS NOT NULL AND jd.fecha >= %s")
        params.append(desde)
    if hasta:
        where.append("jd.fecha IS NOT NULL AND jd.fecha <= %s")
        params.append(hasta)

    sql = f"""
    SELECT
      jc.doc_id, jc.chunk_id, jc.section, jc.text,
      1 - (jc.embedding <=> %s::vector) AS score,
      jd.titulo, jd.tribunal, jd.fecha, jd.link_origen, jd.s3_key_document
    FROM ia_jurischunk jc
    JOIN ia_jurisdocument jd ON jd.doc_id = jc.doc_id
    WHERE {" AND ".join(where)}
    ORDER BY jc.embedding <=> %s::vector
    LIMIT %s;
    """
    params_final = [emb_lit] + params + [emb_lit, int(k)]

    with connection.cursor() as cur:
        cur.execute(sql, params_final)
        rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        doc_url = r[8]
        text_clean = clean_urls_in_text(r[3] or "")
        out.append({
            "doc_id": r[0],
            "chunk_id": r[1],
            "section": r[2],
            "text": text_clean,
            "score": float(r[4]),
            "titulo": r[5],
            "tribunal": r[6],
            "fecha": r[7].isoformat() if r[7] else None,
            "link_origen": doc_url,
            "s3_key_document": r[9],
        })
    return out
