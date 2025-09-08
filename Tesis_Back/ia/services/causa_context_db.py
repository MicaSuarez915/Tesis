# ia/services/causa_context_db.py
from typing import List, Optional
from django.utils.timezone import localtime
from django.core.exceptions import ObjectDoesNotExist
from typing import List
from django.utils.timezone import localtime
from django.db.models import Prefetch
from django.core.exceptions import ObjectDoesNotExist

from causa.models import (
    Causa, CausaParte, CausaProfesional, Documento, EventoProcesal
)

def _fmt_dt(dt):
    if not dt:
        return ""
    # Fecha para Date/DateTime
    try:
        return localtime(dt).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)

def build_causa_context_db(
    causa_id: int,
    *,
    include_partes: bool = True,
    include_profesionales: bool = True,
    include_eventos: bool = True,
    include_docs_metadata: bool = True,
    max_chars: int = 30000
) -> str:
    """
    Consolida SOLO datos de DB para alimentar el resumen:
      - Causa (carátula, expte, fuero, jurisdicción, estado, fechas)
      - Partes (y rol)
      - Profesionales (y rol_profesional)
      - Eventos procesales (cronológico)
      - Documentos (metadatos: título, fecha/creado_en)
    """

    try:
        causa = (
            Causa.objects
            .prefetch_related(
                Prefetch("causa_partes", queryset=CausaParte.objects.select_related("parte", "rol_parte")),
                Prefetch("causas_profesionales", queryset=CausaProfesional.objects.select_related("profesional")),
                Prefetch("eventos", queryset=EventoProcesal.objects.all().order_by("fecha", "id")),
                Prefetch("documentos", queryset=Documento.objects.all().order_by("fecha", "creado_en", "id")),
            )
            .get(pk=causa_id)
        )
    except ObjectDoesNotExist:
        return f"[ERROR] La causa {causa_id} no existe."

    blocks: List[str] = []

    # ===== Encabezado =====
    header = [
        f"CAUSA #{causa.id} – {getattr(causa, 'caratula', '')}",
        f"Expediente: {getattr(causa, 'numero_expediente', '')}",
        f"Fuero: {getattr(causa, 'fuero', '')} | Jurisdicción: {getattr(causa, 'jurisdiccion', '')}",
        f"Fecha inicio: {getattr(causa, 'fecha_inicio', '')} | Estado: {getattr(causa, 'estado', '')}",
    ]
    blocks.append("\n".join(header))

    # ===== Partes =====
    if include_partes:
        partes_lines: List[str] = []
        for cp in causa.causa_partes.all():
            rol = getattr(cp.rol_parte, "nombre", "") if getattr(cp, "rol_parte", None) else ""
            parte = getattr(cp, "parte", None)
            parte_nombre = getattr(parte, "nombre_razon_social", "") if parte else ""
            obs = (getattr(cp, "observaciones", "") or "").strip()
            partes_lines.append(f"- {rol}: {parte_nombre}" + (f" ({obs})" if obs else ""))
        if partes_lines:
            blocks.append("PARTES Y ROLES:\n" + "\n".join(partes_lines))

    # ===== Profesionales =====
    if include_profesionales:
        prof_lines: List[str] = []
        for cp in causa.causas_profesionales.all():
            prof = getattr(cp, "profesional", None)
            nombre = f"{getattr(prof, 'nombre', '')} {getattr(prof, 'apellido', '')}".strip() if prof else "Profesional"
            rol_prof = getattr(cp, "rol_profesional", "") or ""
            prof_lines.append(f"- {nombre} ({rol_prof})")
        if prof_lines:
            blocks.append("PROFESIONALES:\n" + "\n".join(prof_lines))

    # ===== Eventos procesales =====
    if include_eventos:
        eventos_lines: List[str] = []
        for ev in causa.eventos.all():
            titulo = getattr(ev, "titulo", "") or "Evento"
            fecha = _fmt_dt(getattr(ev, "fecha", None))
            desc = (getattr(ev, "descripcion", "") or "").strip()
            eventos_lines.append(f"- [{fecha}] {titulo}: {desc}")
        if eventos_lines:
            blocks.append("EVENTOS PROCESALES (cronológico):\n" + "\n".join(eventos_lines))

    # ===== Documentos =====
    if include_docs_metadata:
        docs_lines: List[str] = []
        for d in causa.documentos.all():
            titulo = getattr(d, "titulo", "") or f"Documento {getattr(d, 'id', '')}"
            # Mostrar fecha si existe, si no, creado_en
            fecha = getattr(d, "fecha", None)
            fstr = _fmt_dt(fecha) if fecha else _fmt_dt(getattr(d, "creado_en", None))
            docs_lines.append(f"- {titulo} – fecha: {fstr}")
        if docs_lines:
            blocks.append("DOCUMENTOS (metadatos):\n" + "\n".join(docs_lines))

    full = ("\n\n".join(blocks)).strip()
    if max_chars:
        full = full[:max_chars]
    return full
