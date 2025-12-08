SYS = (
    "Eres un asistente jurídico para investigación de jurisprudencia. "
    "Responde en español claro y preciso. "
    "Usa **citas** con los IDs entre [] exactamente como aparecen en el contexto. "
    "No inventes jurisprudencia ni citas. Si falta contexto, dilo."
)

def build_prompt(user_query: str, hits: list, max_chars_ctx: int = 10000) -> list:
    ctx_parts, used = [], 0
    for idx, h in enumerate(hits, 1):
        # ✅ Sin URL en el header
        header = f"[Fuente {idx}] {h['titulo']} — {h.get('tribunal') or ''} — {h.get('fecha') or 's/f'}"
        block = f"{header}\n{h['text'].strip()}\n"
        if used + len(block) > max_chars_ctx:
            continue
        ctx_parts.append(block); used += len(block)

    context = "\n\n".join(ctx_parts) or "(sin contexto)"
    user = (
        f"Consulta del usuario:\n{user_query}\n\n"
        "Fragmentos relevantes de jurisprudencia, leyes y doctrina:\n"
        f"{context}\n\n"
        "Instrucciones de redacción:\n"
        "- Redactá una respuesta clara, formal y concisa, con tono de análisis jurídico.\n"
        "- Referenciá las fuentes usando el formato [Fuente 1], [Fuente 2], etc.\n"
        "- NUNCA incluyas URLs, links ni direcciones web en tu respuesta.\n"
        "- Las citas con URLs se manejan automáticamente en un campo separado.\n"
        "- No incluyas la etiqueta 'TL;DR' ni ningún encabezado numérico (como '1)' o '3)').\n"
        "- Si el contexto es insuficiente, indicá explícitamente que no se encontraron antecedentes o conclusiones suficientes.\n"
        "- Si es posible, explicá brevemente por qué los fragmentos no son concluyentes.\n"
        "- No enumeres ni transcribas las citas al final: esas se entregarán por separado en otro campo JSON.\n\n"
        "Formato de salida esperado:\n"
        "Una única respuesta estructurada en párrafos con el análisis y conclusiones, sin URLs, sin listas numeradas ni secciones de 'Citas'."
    )
    return [
        {"role": "system", "content": SYS},
        {"role": "user", "content": user},
    ]
