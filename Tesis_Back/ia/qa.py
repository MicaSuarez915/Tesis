SYS = (
    "Eres un asistente jurídico para investigación de jurisprudencia. "
    "Responde en español claro y preciso. "
    "Usa **citas** con los IDs entre [] exactamente como aparecen en el contexto. "
    "No inventes jurisprudencia ni citas. Si falta contexto, dilo."
)

def build_prompt(user_query: str, hits: list, max_chars_ctx: int = 10000) -> list:
    ctx_parts, used = [], 0
    for h in hits:
        url = h.get("link_origen") or "(sin URL)"
        header = f"[{h['doc_id']}#{h['chunk_id']}] {h['titulo']} — {h.get('tribunal') or ''} — {h.get('fecha') or 's/f'} — URL: {url}"
        block = f"{header}\n{h['text'].strip()}\n"
        if used + len(block) > max_chars_ctx:
            continue
        ctx_parts.append(block); used += len(block)

    context = "\n\n".join(ctx_parts) or "(sin contexto)"
    user = (
        f"Consulta:\n{user_query}\n\n"
        "Fragmentos relevantes (usa los IDs entre [] en las citas):\n"
        f"{context}\n\n"
        "Salida:\n"
        "1) TL;DR (3–6 bullets)\n"
        "2) Análisis (criterios, precedentes convergentes/divergentes)\n"
        "3) **Citas**: lista final reutilizando exactamente los IDs del contexto y mostrando el URL cuando exista.\n"
        "Si el contexto es insuficiente para concluir, dilo."
    )
    return [
        {"role": "system", "content": SYS},
        {"role": "user", "content": user},
    ]
