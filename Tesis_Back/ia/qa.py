SYS = (
    "Sos un asistente experto en derecho laboral argentino. Analizás jurisprudencia y normativa con precisión profesional."
    "Responde en español claro y preciso. "
    "Usa **citas** con los IDs entre [] exactamente como aparecen en el contexto. "
    "No inventes jurisprudencia ni citas. Si falta contexto, dilo."
)

def build_prompt(user_query: str, hits: list, causa_context: str = "", max_chars_ctx: int = 12000) -> list:
    """
    Construye el prompt optimizado para el asistente jurídico experto.
    """
    ctx_parts = []
    used = 0
    
    # Si hay contexto de causa, agregarlo primero
    if causa_context:
        ctx_parts.append("=== CONTEXTO DE LA CAUSA ===")
        ctx_parts.append(causa_context)
        ctx_parts.append("")
        used += len(causa_context)
    
    # Clasificar fuentes
    local_hits = []
    web_hits = []
    causa_docs = []
    
    for h in hits:
        doc_id = h.get('doc_id', '')
        if 'causa_doc::' in doc_id:
            causa_docs.append(h)
        elif h.get('source') == 'tavily' or 'tavily' in doc_id.lower():
            web_hits.append(h)
        else:
            local_hits.append(h)
    
    # Documentos de la causa
    if causa_docs:
        ctx_parts.append("=== DOCUMENTOS DE LA CAUSA ===")
        for idx, h in enumerate(causa_docs, 1):
            header = f"\n[Doc {idx}] {h['titulo']}"
            block = f"{header}\n{h['text'].strip()}\n"
            if used + len(block) > max_chars_ctx:
                continue
            ctx_parts.append(block)
            used += len(block)
    
    # Jurisprudencia local
    base_idx = len(causa_docs)
    if local_hits:
        ctx_parts.append("\n=== JURISPRUDENCIA Y DOCTRINA ===")
        for idx, h in enumerate(local_hits, base_idx + 1):
            tribunal = h.get('tribunal', '')
            fecha = h.get('fecha', '')
            header = f"\n[Fuente {idx}] {h['titulo']}"
            if tribunal:
                header += f" — {tribunal}"
            if fecha:
                header += f" — {fecha}"
            
            block = f"{header}\n{h['text'].strip()}\n"
            if used + len(block) > max_chars_ctx:
                continue
            ctx_parts.append(block)
            used += len(block)
    
    # Fuentes web
    base_idx = base_idx + len(local_hits)
    if web_hits:
        ctx_parts.append("\n=== INFORMACIÓN COMPLEMENTARIA ===")
        for idx, h in enumerate(web_hits, base_idx + 1):
            header = f"\n[Web {idx}] {h.get('titulo', 'Fuente web')}"
            block = f"{header}\n{h['text'].strip()}\n"
            if used + len(block) > max_chars_ctx:
                continue
            ctx_parts.append(block)
            used += len(block)
    
    context = "\n".join(ctx_parts) if ctx_parts else ""
    
    # Prompt más directo y simple
    system_prompt = """Sos un abogado laboralista senior de la Provincia de Buenos Aires con 15+ años de experiencia.

Tu trabajo es analizar jurisprudencia y proporcionar respuestas fundamentadas en las fuentes disponibles.

REGLAS CRÍTICAS:
- Analizá TODAS las fuentes proporcionadas
- Cita las fuentes como [Fuente X], [Doc X] o [Web X]
- NUNCA digas que no tenés acceso a fuentes o internet
- NUNCA incluyas URLs en tu respuesta
- Si hay contexto de causa, aplicá la jurisprudencia a ese caso específico
- Escribí en párrafos fluidos, sin listas numeradas
- Tono profesional pero claro"""

    user_prompt = f"""CONSULTA: {user_query}

FUENTES DISPONIBLES:
{context}

INSTRUCCIONES:
1. Analizá las fuentes proporcionadas
2. Si hay contexto de causa, conectá la jurisprudencia con el caso
3. Cita cada fuente como [Fuente X]
4. NO incluyas URLs en tu texto
5. Respondé en párrafos corridos

IMPORTANTE: Tenés {len(hits)} fuentes disponibles. Usalas todas para tu análisis."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]