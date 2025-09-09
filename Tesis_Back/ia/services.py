import json
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.conf import settings
from .gpt_client import chat
from causa.models import Documento, Causa, CausaParte, CausaProfesional, EventoProcesal  # Add this import for Documento, Causa, CausaParte, and EventoProcesal models
from django.db.models import Count, Q, Max
from datetime import timedelta

# === 1) Tu “vista” de DB para dar contexto estructurado ===

def build_db_context(topic: str, filters: dict):
    """
    Filtros soportados (opcionales):
      - creado_por (int)
      - estado (str o lista de str)           # 'abierta', 'en_tramite', 'con_sentencia', 'cerrada', 'archivada'
      - jurisdiccion (str)
      - fuero (str)
      - desde (YYYY-MM-DD)    -> filtra Causa.fecha_inicio >= desde
      - hasta (YYYY-MM-DD)    -> filtra Causa.fecha_inicio <= hasta
      - q / search (str)      -> busca en número de expediente y carátula
      - parte_id (int)        -> causas que incluyan esa parte
      - rol_parte (str)       -> causas con esa denominación de rol (por nombre)
      - profesional_id (int)  -> causas vinculadas a ese profesional
      - rol_profesional (str) -> 'patrocinante' | 'apoderado' | 'colaborador'
    """
    now = timezone.now()
    hoy = now.date()

    # --------- Query base ---------
    qs = Causa.objects.all()

    # --- Filtros ---
    creado_por      = filters.get("creado_por")
    estado          = filters.get("estado")
    jurisdiccion    = filters.get("jurisdiccion")
    fuero           = filters.get("fuero")
    search_text     = filters.get("q") or filters.get("search")
    desde           = parse_date(filters.get("desde")) if filters.get("desde") else None
    hasta           = parse_date(filters.get("hasta")) if filters.get("hasta") else None
    parte_id        = filters.get("parte_id")
    rol_parte       = filters.get("rol_parte")          # nombre del rol
    profesional_id  = filters.get("profesional_id")
    rol_profesional = filters.get("rol_profesional")    # 'patrocinante'|'apoderado'|'colaborador'

    if creado_por:
        qs = qs.filter(creado_por_id=creado_por)

    if estado:
        if isinstance(estado, (list, tuple, set)):
            qs = qs.filter(estado__in=list(estado))
        else:
            qs = qs.filter(estado=estado)

    if jurisdiccion:
        qs = qs.filter(jurisdiccion__iexact=jurisdiccion)

    if fuero:
        qs = qs.filter(fuero__iexact=fuero)

    if desde:
        qs = qs.filter(fecha_inicio__gte=desde)
    if hasta:
        qs = qs.filter(fecha_inicio__lte=hasta)

    if search_text:
        qs = qs.filter(
            Q(numero_expediente__icontains=search_text) |
            Q(caratula__icontains=search_text)
        )

    if parte_id:
        qs = qs.filter(partes__parte_id=parte_id)

    if rol_parte:
        qs = qs.filter(partes__rol_parte__nombre__iexact=rol_parte)

    if profesional_id:
        qs = qs.filter(profesionales__profesional_id=profesional_id)

    if rol_profesional:
        qs = qs.filter(profesionales__rol_profesional=rol_profesional)

    qs = qs.distinct()

    # --------- KPIs ---------
    total_causas = qs.count()
    # Conteo por estado (devuelve solo los presentes en la selección)
    estados_raw = qs.values("estado").annotate(n=Count("id"))
    estados = {row["estado"]: row["n"] for row in estados_raw}
    # Derivados útiles
    cerradas = estados.get("cerrada", 0) + estados.get("archivada", 0)
    abiertas = total_causas - cerradas

    # Causas sin movimientos en 90 días (mirando eventos.fecha)
    qs_sin_mov = qs.annotate(ultima_fecha=Max("eventos__fecha")).filter(
        Q(ultima_fecha__lt=hoy - timedelta(days=90)) | Q(ultima_fecha__isnull=True)
    )
    sin_mov_90 = qs_sin_mov.count()

    # --------- Distribuciones ---------
    por_fuero = list(
        qs.values("fuero")
          .annotate(n=Count("id"))
          .order_by("-n")[:10]
    )
    por_jurisdiccion = list(
        qs.values("jurisdiccion")
          .annotate(n=Count("id"))
          .order_by("-n")[:10]
    )

    # --------- Top Partes y Profesionales ---------
    top_partes = list(
        CausaParte.objects.filter(causa__in=qs)
        .values("parte__nombre_razon_social")
        .annotate(n=Count("causa_id", distinct=True))
        .order_by("-n")[:10]
    )
    top_roles_parte = list(
        CausaParte.objects.filter(causa__in=qs)
        .values("rol_parte__nombre")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    )
    top_profesionales = list(
        CausaProfesional.objects.filter(causa__in=qs)
        .values("profesional__apellido", "profesional__nombre")
        .annotate(n=Count("causa_id", distinct=True))
        .order_by("-n")[:10]
    )
    top_roles_profesional = list(
        CausaProfesional.objects.filter(causa__in=qs)
        .values("rol_profesional")
        .annotate(n=Count("id"))
        .order_by("-n")
    )

    # --------- Próximos eventos (14 días) ---------
    proximos_eventos_qs = (
        EventoProcesal.objects
        .filter(causa__in=qs, fecha__gte=hoy, fecha__lte=hoy + timedelta(days=14))
        .select_related("causa")
        .order_by("fecha")[:15]
    )
    proximos_eventos = [
        {
            "id": ev.id,
            "fecha": ev.fecha.isoformat() if ev.fecha else None,
            "plazo_limite": ev.plazo_limite.isoformat() if ev.plazo_limite else None,
            "titulo": ev.titulo,
            "descripcion": ev.descripcion[:280] if ev.descripcion else "",
            "causa_id": ev.causa_id,
            "causa": ev.causa.caratula or ev.causa.numero_expediente,
        }
        for ev in proximos_eventos_qs
    ]

    # Vencimientos pasados (plazo_limite vencido)
    vencidos_qs = EventoProcesal.objects.filter(causa__in=qs, plazo_limite__lt=hoy)
    vencidos_count = vencidos_qs.count()

    # --------- Últimos documentos ---------
    ult_docs_qs = (
        Documento.objects.filter(causa__in=qs)
        .select_related("causa")
        .order_by("-creado_en")[:15]
    )
    ultimos_documentos = [
        {
            "id": d.id,
            "titulo": d.titulo,
            "causa_id": d.causa_id,
            "causa": d.causa.caratula or d.causa.numero_expediente,
            "fecha": d.fecha.isoformat() if d.fecha else None,
            "creado_en": d.creado_en.isoformat() if d.creado_en else None,
        }
        for d in ult_docs_qs
    ]

    # --------- Muestra de causas (para que el LLM tenga ejemplos) ---------
    muestra_causas = list(
        qs.values(
            "id", "numero_expediente", "caratula", "estado",
            "jurisdiccion", "fuero", "fecha_inicio", "creado_en"
        ).order_by("-creado_en")[:20]
    )
    # Normalizar fechas a ISO
    for c in muestra_causas:
        if c.get("fecha_inicio"):
            c["fecha_inicio"] = c["fecha_inicio"].isoformat()
        if c.get("creado_en"):
            c["creado_en"] = c["creado_en"].isoformat()

    # --------- Respuesta final ---------
    return {
        "topic": topic,
        "filters": filters,
        "kpis": {
            "total_causas": total_causas,
            "abiertas": abiertas,
            "cerradas_o_archivadas": cerradas,
            "por_estado": estados,                   # {'abierta': X, 'en_tramite': Y, ...}
            "sin_movimientos_90d": sin_mov_90,
            "vencimientos_pasados": vencidos_count,
        },
        "distribuciones": {
            "por_fuero": por_fuero,                 # [{'fuero':'...', 'n':...}, ...]
            "por_jurisdiccion": por_jurisdiccion,   # [{'jurisdiccion':'...', 'n':...}, ...]
        },
        "top": {
            "partes": top_partes,                   # [{'parte__nombre_razon_social': '...', 'n': ...}, ...]
            "roles_parte": top_roles_parte,         # [{'rol_parte__nombre': 'actor', 'n': ...}, ...]
            "profesionales": top_profesionales,     # [{'profesional__apellido': '...', 'profesional__nombre':'...', 'n': ...}]
            "roles_profesional": top_roles_profesional,
        },
        "proximos_eventos_14d": proximos_eventos,
        "ultimos_documentos": ultimos_documentos,
        "muestra_causas": muestra_causas,
        "generated_at": now.isoformat(),
    }

# === 2) Prompts ===
def build_summary_prompt(db_json: dict) -> str:
    return (
        "Eres un analista senior. Con el SIGUIENTE JSON de datos estructurados, "
        "genera un resumen ejecutivo en español, preciso y SIN INVENTAR.\n\n"
        "Formato Markdown con secciones:\n"
        "1) TL;DR (máx. 5 bullets)\n"
        "2) Hechos clave (cifras/fechas exactas)\n"
        "3) Métricas (tabla breve si aplica)\n"
        "4) Riesgos/lagunas\n"
        "5) Próximos pasos (máx. 5)\n\n"
        "Usa SOLO lo que está en el JSON; si falta info, dilo explícitamente.\n\n"
        f"JSON:\n{json.dumps(db_json, ensure_ascii=False)}"
    )

def build_verifier_prompt(summary_markdown: str, db_json: dict) -> str:
    return (
        "Eres un verificador de hechos. Revisa el RESUMEN (Markdown) contra el JSON de datos.\n"
        "Responde SOLO en JSON con:\n"
        '{"veredicto":"ok|warning|fail",'
        '"issues":[{"tipo":"dato_inconsistente|inferencia_no_soportada|omision","detalle":"..."}]}\n\n'
        f"RESUMEN:\n{summary_markdown}\n\n"
        f"DATOS_JSON:\n{json.dumps(db_json, ensure_ascii=False)}"
    )

# === 3) Orquestador ===
def run_summary_and_verification(topic: str, filters: dict):
    db_json = build_db_context(topic, filters)

    # --- SUMMARIZER (GPT “grande”: gpt-4o recomendado) ---
    summary = chat(
        model=settings.GPT_SUMMARIZER_MODEL,
        messages=[
            {"role": "system", "content": "Eres un experto en resúmenes fiables, concisos y verificables."},
            {"role": "user", "content": build_summary_prompt(db_json)}
        ],
        max_tokens=settings.SUMMARY_MAX_TOKENS
    )

    # --- VERIFIER (GPT “ligero”: gpt-4o-mini recomendado) ---
    verifier_json_text = chat(
        model=settings.GPT_VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "Eres un verificador estricto de factualidad y coherencia."},
            {"role": "user", "content": build_verifier_prompt(summary, db_json)}
        ],
        # Pedimos JSON estructurado
        response_format={"type": "json_object"},
        max_tokens=settings.VERIFIER_MAX_TOKENS,
        temperature=0.0
    )

    try:
        parsed = json.loads(verifier_json_text)
        verdict = parsed.get("veredicto", "warning")
        issues = parsed.get("issues", [])
    except Exception:
        verdict = "warning"
        issues = [{"tipo":"parser_error","detalle":"El verificador no devolvió JSON válido","raw":verifier_json_text[:800]}]

    return db_json, summary, verdict, issues, verifier_json_text


def build_case_context(causa_id: int) -> dict:
    hoy = timezone.now().date()

    causa = (
        Causa.objects
        .select_related("creado_por")
        .get(pk=causa_id)
    )

    # Partes con rol
    partes = list(
        CausaParte.objects
        .filter(causa_id=causa_id)
        .select_related("parte", "rol_parte")
        .values(
            "parte_id",
            "parte__tipo_persona",
            "parte__nombre_razon_social",
            "rol_parte__nombre",
            "observaciones",
        )
        .order_by("rol_parte__nombre", "parte__nombre_razon_social")
    )

    # Profesionales con rol
    profesionales = list(
        CausaProfesional.objects
        .filter(causa_id=causa_id)
        .select_related("profesional")
        .values(
            "profesional_id",
            "profesional__apellido",
            "profesional__nombre",
            "rol_profesional",
        )
        .order_by("rol_profesional", "profesional__apellido", "profesional__nombre")
    )

    # Eventos: últimos 20 y próximos 10
    eventos_hist = list(
        EventoProcesal.objects
        .filter(causa_id=causa_id, fecha__lte=hoy)
        .values("id", "titulo", "descripcion", "fecha", "plazo_limite")
        .order_by("-fecha", "-id")[:20]
    )
    eventos_prox = list(
        EventoProcesal.objects
        .filter(causa_id=causa_id, fecha__gt=hoy)
        .values("id", "titulo", "descripcion", "fecha", "plazo_limite")
        .order_by("fecha", "id")[:10]
    )
    vencidos_count = EventoProcesal.objects.filter(causa_id=causa_id, plazo_limite__lt=hoy).count()

    # Documentos (últimos 15)
    docs = list(
        Documento.objects
        .filter(causa_id=causa_id)
        .values("id", "titulo", "fecha", "creado_en")
        .order_by("-creado_en")[:15]
    )

    # KPIs de la causa
    dias_abierta = None
    if causa.fecha_inicio:
        dias_abierta = (hoy - causa.fecha_inicio).days

    ultima_act = (
        EventoProcesal.objects.filter(causa_id=causa_id).aggregate(ultima=Max("fecha"))["ultima"]
        or Documento.objects.filter(causa_id=causa_id).aggregate(ultima=Max("creado_en"))["ultima"]
    )

    ctx = {
        "causa": {
            "id": causa.id,
            "numero_expediente": causa.numero_expediente,
            "caratula": causa.caratula,
            "fuero": causa.fuero,
            "jurisdiccion": causa.jurisdiccion,
            "estado": causa.estado,
            "fecha_inicio": causa.fecha_inicio.isoformat() if causa.fecha_inicio else None,
            "creado_por_id": causa.creado_por_id,
            "creado_en": causa.creado_en.isoformat() if causa.creado_en else None,
            "actualizado_en": causa.actualizado_en.isoformat() if causa.actualizado_en else None,
        },
        "kpis": {
            "dias_abierta": dias_abierta,
            "vencimientos_pasados": vencidos_count,
            "ultima_actualizacion": ultima_act.isoformat() if ultima_act else None,
        },
        "partes": partes,
        "profesionales": profesionales,
        "eventos": {
            "historicos": _normalize_dates(eventos_hist),
            "proximos_14d": _normalize_dates(eventos_prox),
        },
        "documentos": _normalize_dates(docs),
        "generated_at": timezone.now().isoformat(),
    }
    return ctx


def _normalize_dates(items):
    out = []
    for it in items:
        it = dict(it)
        for k in ("fecha", "plazo_limite", "creado_en"):
            if k in it and it[k] is not None:
                it[k] = it[k].isoformat()
        # recortar descripciones largas para evitar tokens de más
        if "descripcion" in it and it["descripcion"]:
            it["descripcion"] = (it["descripcion"][:600] + "…") if len(it["descripcion"]) > 600 else it["descripcion"]
        out.append(it)
    return out


# -------------------- PROMPTS (CAUSA) --------------------
def build_case_summary_prompt(ctx: dict) -> str:
    return (
        "Eres un analista jurídico. Redacta un RESUMEN EJECUTIVO de la causa, en español, "
        "preciso y SIN INVENTAR, usando EXCLUSIVAMENTE el JSON provisto.\n\n"
        "Formato Markdown con secciones:\n"
        "1) TL;DR (máx. 5 bullets)\n"
        "2) Datos de la causa (expediente, fuero, jurisdicción, estado, fechas)\n"
        "3) Partes y roles (lista breve)\n"
        "4) Profesionales y roles (lista breve)\n"
        "5) Cronología (eventos clave; últimos y próximos)\n"
        "6) Documentos recientes (si hay)\n"
        "7) Riesgos/lagunas (qué falta/vence pronto)\n"
        "8) Próximos pasos (máx. 5)\n\n"
        "Si algo no está en el JSON, dilo como 'no consta'.\n\n"
        f"JSON:\n{json.dumps(ctx, ensure_ascii=False)}"
    )


def build_case_verifier_prompt(summary_md: str, ctx: dict) -> str:
    return (
        "Eres un verificador de hechos. Revisa el RESUMEN (Markdown) contra el JSON de la causa y detecta:\n"
        "- datos inconsistentes o cifras/fechas inventadas\n"
        "- inferencias no soportadas\n"
        "- omisiones críticas\n"
        "Responde SOLO en JSON con:\n"
        '{"veredicto":"ok|warning|fail",'
        '"issues":[{"tipo":"dato_inconsistente|inferencia_no_soportada|omision","detalle":"..."}]}\n\n'
        f"RESUMEN:\n{summary_md}\n\n"
        f"DATOS_JSON:\n{json.dumps(ctx, ensure_ascii=False)}"
    )


# -------------------- ORQUESTA: RESUMIR + VERIFICAR (CAUSA) --------------------
def run_case_summary_and_verification(causa_id: int):
    ctx = build_case_context(causa_id)

    summary = chat(
        model=settings.GPT_SUMMARIZER_MODEL,            # p.ej. "gpt-4o"
        messages=[
            {"role": "system", "content": "Eres un experto en resúmenes fiables, concisos y verificables."},
            {"role": "user", "content": build_case_summary_prompt(ctx)},
        ],
        max_tokens=settings.SUMMARY_MAX_TOKENS,
        temperature=0.2
    )

    verifier_raw = chat(
        model=settings.GPT_VERIFIER_MODEL,              # p.ej. "gpt-4o-mini"
        messages=[
            {"role": "system", "content": "Eres un verificador estricto de factualidad y coherencia."},
            {"role": "user", "content": build_case_verifier_prompt(summary, ctx)},
        ],
        response_format={"type": "json_object"},
        max_tokens=settings.VERIFIER_MAX_TOKENS,
        temperature=0.0
    )

    try:
        parsed = json.loads(verifier_raw)
        verdict = parsed.get("veredicto", "warning")
        issues = parsed.get("issues", [])
    except Exception:
        verdict = "warning"
        issues = [{"tipo": "parser_error", "detalle": "El verificador no devolvió JSON válido", "raw": verifier_raw[:800]}]

    return ctx, summary, verdict, issues, verifier_raw