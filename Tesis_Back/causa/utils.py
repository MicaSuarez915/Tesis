def generar_grafo_desde_bd(causa):
    """
    Devuelve un JSON (dict) con nodes/edges a partir de lo que haya en BD.
    Por defecto solo genera nodos; las aristas las define el front más tarde.
    """
    nodes = []
    edges = []  # el front las irá agregando

    # NODOS de Partes
    for p in causa.partes.select_related("parte").all():
        parte = p.parte
        nodes.append({
            "id": f"parte-{parte.id}",
            "type": "parte",
            "data": {"label": parte.nombre_razon_social},
            "position": {"x": 0, "y": 0},  # opcional, el front puede moverlos
        })

    # NODOS de Profesionales
    for cp in causa.profesionales.select_related("profesional").all():
        prof = cp.profesional
        nodes.append({
            "id": f"prof-{prof.id}",
            "type": "profesional",
            "data": {"label": f"{prof.apellido}, {prof.nombre}".strip(", ")},
            "position": {"x": 0, "y": 0},
        })

    # NODOS de Documentos
    for d in causa.documentos.all():
        nodes.append({
            "id": f"doc-{d.id}",
            "type": "documento",
            "data": {"label": d.titulo},
            "position": {"x": 0, "y": 0},
        })

    # NODOS de Eventos
    for ev in causa.eventos.all():
        nodes.append({
            "id": f"ev-{ev.id}",
            "type": "evento",
            "data": {"label": ev.titulo},
            "position": {"x": 0, "y": 0},
        })

    return {"nodes": nodes, "edges": edges}
