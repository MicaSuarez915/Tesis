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
        header = f"[ {h['titulo']} — {h.get('tribunal') or ''} — {h.get('fecha') or 's/f'} — URL: {url}"
        block = f"{header}\n{h['text'].strip()}\n"
        if used + len(block) > max_chars_ctx:
            continue
        ctx_parts.append(block); used += len(block)

    context = "\n\n".join(ctx_parts) or "(sin contexto)"
    user = (
        f"Consulta del usuario:\n{user_query}\n\n"
        "Fragmentos relevantes de jurisprudencia, leyes y doctrina (usa la URL de los IDs entre [ ] para referenciar en el texto si lo creés necesario):\n"
        f"{context}\n\n"
        "Instrucciones de redacción:\n"
        "- Redactá una respuesta clara, formal y concisa, con tono de análisis jurídico.\n"
        "- No incluyas la etiqueta 'TL;DR' ni ningún encabezado numérico (como '1)' o '3)').\n"
        "- Si el contexto es insuficiente, indicá explícitamente que no se encontraron antecedentes o conclusiones suficientes.\n"
        "- Si es posible, explicá brevemente por qué los fragmentos no son concluyentes.\n"
        "- No enumeres ni transcribas las citas al final: esas se entregarán por separado en otro campo JSON.\n"
        "- Podés mencionar la URL de los IDs entre corchetes [ ] dentro del análisis si aportan respaldo (no pongas los IDs en el texto).\n\n"
        "Formato de salida esperado:\n"
        "Una única respuesta estructurada en párrafos con el análisis y conclusiones, sin listas numeradas ni secciones de 'Citas'."
    )
    return [
        {"role": "system", "content": SYS},
        {"role": "user", "content": user},
    ]
