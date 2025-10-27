
from functools import lru_cache
import os
from unittest import result
import boto3
from django.shortcuts import render, get_object_or_404
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


# Create your views here.
    
import openai
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import viewsets
from rest_framework import permissions
from rest_framework.generics import GenericAPIView
from django.conf import settings
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SummaryRun, VerificationResult, Conversation, Message, IdempotencyKey
from causa.models import Causa
from causa.models import Documento
from .serializers import AskJurisResponseSerializer, SummaryRunSerializer, SummaryGenerateSerializer, VerificationResultSerializer, GrammarCheckResponseSerializer, GrammarCheckRequestSerializer, AskJurisRequestSerializer,  ConversationListItemSerializer, ConversationDetailSerializer, ConversationCreateRequestSerializer, ConversationMessageCreateRequestSerializer, ConversationMessageCreateResponseSerializer, AskJurisRequestUnionSerializer, ConversationResponseSerializer
from django.utils import timezone

# Importa el orquestador que ya definimos antes (GPT u Ollama)
# Debe existir en ia/services.py: run_summary_and_verification(topic, filters) -> (db_json, summary_text, verdict, issues, raw_json_text)
from .services import run_summary_and_verification, run_case_summary_and_verification

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, extend_schema_view, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from django.db import transaction
from django.db.models.functions import Coalesce

from openai import OpenAI


@lru_cache(maxsize=1)
def get_openai_client():
    return openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

GEN_REQ_EXAMPLE = OpenApiExample(
    "Ejemplo de request",
    value={
        "topic": "Resumen mensual CABA",
        "filters": {
            "estado": "en_tramite",
            "jurisdiccion": "CABA",
            "desde": "2025-08-01",
            "hasta": "2025-09-08",
            "q": "Banco"
        }
    },
    request_only=True,
)

GEN_RES_EXAMPLE = OpenApiExample(
    "Ejemplo de respuesta (201)",
    value={
        "id": 41,
        "topic": "Resumen mensual CABA",
        "filters": {"estado": "en_tramite", "jurisdiccion": "CABA"},
        "db_snapshot": {"kpis": {"total_causas": 10, "abiertas": 7, "cerradas_o_archivadas": 3}},
        "prompt": "(generado internamente en ia.services)",
        "summary_text": "## TL;DR\n- ...",
        "citations": [],
        "created_at": "2025-09-09T20:11:00Z",
        "created_by": 3,
        "verification": {
            "verdict": "ok",
            "issues": []
        }
    },
    response_only=True,
)

REVERIFY_RES_EXAMPLE = OpenApiExample(
    "Ejemplo de respuesta (200 reverify)",
    value={
        "verdict": "warning",
        "issues": [
            {"tipo": "omision", "detalle": "No se menciona un evento con plazo vencido."}
        ],
        "raw_output": "{\"veredicto\":\"warning\",\"issues\":[...]}",
        "created_at": "2025-09-09T21:03:11Z"
    },
    response_only=True,
)


@extend_schema_view(
    list=extend_schema(operation_id="ia_summaries_list", summary="Listar resúmenes", tags=["IA"],
                       responses={200: SummaryRunSerializer}),
    retrieve=extend_schema(operation_id="ia_summaries_retrieve", summary="Obtener un resumen por ID", tags=["IA"],
                           responses={200: SummaryRunSerializer, 404: OpenApiResponse(description="No encontrado")}),
    destroy=extend_schema(operation_id="ia_summaries_delete", summary="Eliminar un resumen", tags=["IA"],
                          responses={204: OpenApiResponse(description="Eliminado")}),
)
class SummaryRunViewSet(viewsets.ModelViewSet):
    queryset = SummaryRun.objects.select_related("created_by", "causa").all()
    serializer_class = SummaryRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Asegurar listado con último movimiento primero
        return (
            super()
            .get_queryset()
            .filter(created_by=self.request.user)
            .annotate(last_activity=Coalesce("updated_at", "created_at"))
            .order_by("-last_activity", "-id")
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Forzar lectura fresca antes de serializar
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    def _update_or_create_verification_result(self, run, verdict, issues, raw_verifier):
        """Método auxiliar para no repetir código."""
        VerificationResult.objects.update_or_create(
            summary_run=run,
            defaults={
                "verdict": verdict,
                "issues": issues,
                "raw_output": raw_verifier
            }
        )

    # ---------- GET: solo obtener por causa ----------
    @extend_schema(
        operation_id="ia_summary_get_by_causa",
        summary="Obtener el último resumen por causa",
        description="Devuelve el último SummaryRun del usuario para la causa. Si no existe, 404.",
        tags=["IA"],
        parameters=[
            OpenApiParameter("causa_id", OpenApiTypes.INT, OpenApiParameter.PATH, description="ID de la causa"),
        ],
        request=None,
        responses={200: SummaryRunSerializer, 404: OpenApiResponse(description="No existe resumen")},
    )
    @action(detail=False, methods=["get"], url_path="by-causa-g/(?P<causa_id>[^/.]+)")
    def get_by_causa(self, request, causa_id: str):
        user = request.user
        causa = get_object_or_404(Causa.objects.filter(creado_por=user), pk=int(causa_id))
        run = (
            SummaryRun.objects
            .filter(causa=causa, created_by=user)
            .annotate(last_activity=Coalesce("updated_at", "created_at"))
            .order_by("-last_activity", "-id")
            .first()
        )
        if not run:
            return Response({"detail": "No existe un resumen para esta causa."},
                            status=status.HTTP_404_NOT_FOUND)
        # Asegurar lectura fresca desde DB
        fresh = SummaryRun.objects.get(pk=run.pk)
        return Response(SummaryRunSerializer(fresh).data, status=status.HTTP_200_OK)

    # ---------- POST: crear por primera vez ----------
    @extend_schema(
        operation_id="ia_summary_create_by_causa",
        summary="Crear resumen por causa (primera vez)",
        description="Crea el SummaryRun para la causa. Si ya existe, 409 (usar PUT para actualizar).",
        tags=["IA"],
        parameters=[
            OpenApiParameter("causa_id", OpenApiTypes.INT, OpenApiParameter.PATH, description="ID de la causa"),
        ],
        request=SummaryGenerateSerializer,   # topic, filters (opcionales según tu diseño)
        responses={
            201: SummaryRunSerializer,
            401: OpenApiResponse(description="No autenticado"),
            404: OpenApiResponse(description="Causa no encontrada"),
            409: OpenApiResponse(description="Ya existe un resumen para esta causa"),
            502: OpenApiResponse(description="Error al generar/verificar"),
        },
    )
    @action(detail=False, methods=["post"], url_path="by-causa-p/(?P<causa_id>[^/.]+)")
    def create_by_causa(self, request, causa_id: str):
        user = request.user
        causa = get_object_or_404(Causa.objects.filter(creado_por=user), pk=int(causa_id))

        if self.get_queryset().filter(causa=causa).exists():
            return Response(
                {"detail": "Ya existe un resumen. Use PUT para actualizar."},
                status=status.HTTP_409_CONFLICT,
            )
        
        topic = f"Resumen de la causa {causa.numero_expediente or causa.id}"
        effective_filters = {"causa_id": causa.id}

        try:
            db_json, summary_text, verdict, issues, raw_verifier = \
                run_summary_and_verification(topic, effective_filters)

            # Usamos transaction.atomic para asegurar que todo se cree o nada
            with transaction.atomic():
                run = SummaryRun.objects.create(
                    topic=topic,
                    causa=causa,
                    filters=effective_filters,
                    db_snapshot=db_json,
                    summary_text=summary_text,
                    created_by=user,
                )
                # Usamos el método auxiliar
                self._update_or_create_verification_result(run, verdict, issues, raw_verifier)

            return Response(SummaryRunSerializer(run).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

    # ---------- PUT: actualizar existente (no crea) ----------
    @extend_schema(
        operation_id="ia_summary_update_by_causa",
        summary="Actualizar resumen por causa (PUT)",
        description="Actualiza el SummaryRun existente de la causa. Si no existe, 404.",
        tags=["IA"],
        parameters=[
            OpenApiParameter("causa_id", OpenApiTypes.INT, OpenApiParameter.PATH, description="ID de la causa"),
        ],
        request=SummaryGenerateSerializer,  # opcional: si no mandan body, podés reutilizar topic/filters actuales
        responses={
            200: SummaryRunSerializer,
            401: OpenApiResponse(description="No autenticado"),
            404: OpenApiResponse(description="No existe resumen para actualizar"),
            502: OpenApiResponse(description="Error al generar/verificar"),
        },
    )
    @action(detail=False, methods=["put"], url_path="by-causa-t/(?P<causa_id>[^/.]+)")
    def update_by_causa(self, request, causa_id: str):
        user = request.user
        causa = get_object_or_404(Causa.objects.filter(creado_por=user), pk=int(causa_id))

        # 1. Obtenemos el resumen existente que vamos a actualizar.
        run = self.get_queryset().filter(causa=causa).first()
        if not run:
            return Response(
                {"detail": "No existe un resumen para esta causa. Use POST para crearlo."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Reutilizamos el 'topic' y 'filters' existentes.
        topic = run.topic
        effective_filters = run.filters or {"causa_id": causa.id}

        try:
            # 3. Regeneramos el resumen con la información más reciente de la DB.
            db_json, summary_text, verdict, issues, raw_verifier = \
                run_summary_and_verification(topic, effective_filters)

            # 4. ACTUALIZAMOS EL OBJETO Y LO GUARDAMOS (LA FORMA CORRECTA)
            run.summary_text = summary_text
            run.db_snapshot = db_json
            run.filters = effective_filters
            run.save() # Esto guarda los cambios en la base de datos.

            # 5. Usamos el método auxiliar para la verificación.
            self._update_or_create_verification_result(run, verdict, issues, raw_verifier)

            return Response(SummaryRunSerializer(run).data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

    @extend_schema(
        operation_id="ia_summaries_reverify",
        summary="Re-verificar un resumen",
        description="Ejecuta SOLO la verificación nuevamente para el SummaryRun indicado.",
        tags=["IA"],
        request=None,
        responses={
            200: VerificationResultSerializer,
            401: OpenApiResponse(description="No autenticado"),
            404: OpenApiResponse(description="SummaryRun no encontrado"),
            502: OpenApiResponse(description="Error al verificar"),
        },
        examples=[REVERIFY_RES_EXAMPLE],
    )
    @action(detail=True, methods=["post"], url_path="reverify")
    def reverify(self, request, pk=None):
        """
        Re-ejecuta SOLO la verificación sobre un SummaryRun existente.
        Útil si cambiás el modelo verificador u optimizás el prompt.
        """
        run = self.get_object()
        from .services import build_verifier_prompt
        
        try:
            verifier_prompt = build_verifier_prompt(run.summary_text, run.db_snapshot)
            
            client = get_openai_client()

            response = client.chat.completions.create(
                model="gpt-4o-mini", 
                messages=[
                    {"role": "system", "content": "Eres un verificador estricto de factualidad y coherencia."},
                    {"role": "user", "content": verifier_prompt}
                ],
                max_tokens=600,
                response_format={"type": "json_object"},
                temperature=0.0
            )
            verifier_json_text = response.choices[0].message.content

        except Exception as e:
            return Response({"error": f"Error en la llamada a la API de IA: {str(e)}"}, status=status.HTTP_502_BAD_GATEWAY)

        verdict, issues = "warning", []
        try:
            parsed = json.loads(verifier_json_text)
            verdict = parsed.get("veredicto", verdict)
            issues = parsed.get("issues", [])
        except json.JSONDecodeError:
            issues = [{"tipo": "parser_error", "detalle": "El verificador no devolvió JSON válido.", "raw": verifier_json_text[:800]}]

        verification_result, created = VerificationResult.objects.update_or_create(
            summary_run=run,
            defaults={"verdict": verdict, "issues": issues, "raw_output": verifier_json_text}
        )

        return Response(VerificationResultSerializer(verification_result).data, status=status.HTTP_200_OK)

# class CaseSummaryView(GenericAPIView):
#     permission_classes = [permissions.IsAuthenticated]
#     serializer_class = SummaryRunSerializer  

#     @extend_schema(
#         operation_id="ia_case_summary_create",
#         description="Genera y persiste un resumen verificado de la causa indicada.",
#         parameters=[
#             OpenApiParameter(
#                 name="causa_id",
#                 type=int,
#                 location=OpenApiParameter.PATH,
#                 description="ID de la causa"
#             )
#         ],
#         request=None,  # no se envía body en este POST
#         responses={
#             201: SummaryRunSerializer,
#             404: OpenApiResponse(description="Causa no encontrada"),
#             502: OpenApiResponse(description="Error al generar el resumen"),
#         },
#         tags=["IA"],
#     )
#     def post(self, request, causa_id: int):
#         try:
#             causa = Causa.objects.get(pk=causa_id)
#         except Causa.DoesNotExist:
#             return Response({"detail": "Causa no encontrada"}, status=status.HTTP_404_NOT_FOUND)

#         try:
#             ctx, summary, verdict, issues, raw = run_case_summary_and_verification(causa.id)
#         except Exception as e:
#             return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

#         run = SummaryRun.objects.create(
#             topic=f"Resumen de causa #{causa.id}",
#             causa=causa,
#             filters={"causa_id": causa.id},
#             db_snapshot=ctx,
#             prompt="(generado internamente en ia.services)",
#             summary_text=summary,
#             created_by=request.user,
#         )
#         VerificationResult.objects.create(
#             summary_run=run,
#             verdict=verdict,
#             issues=issues,
#             raw_output=raw,
#         )
#         return Response(SummaryRunSerializer(run).data, status=status.HTTP_201_CREATED)
    


from .services_grammar import grammar_check_from_text_or_file

class GrammarCheckView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GrammarCheckResponseSerializer 

    @extend_schema(
        operation_id="ia_grammar_check",
        tags=["IA"],
        summary="Chequeo de gramática, ortografía y espaciado (texto o documento)",
        description=(
            "Analiza el texto o documento indicado detectando errores de gramática, "
            "ortografía y espaciado. Devuelve los errores detectados, conteos por página "
            "y el texto completamente corregido."
        ),
        request=GrammarCheckRequestSerializer,
        responses={
            200: GrammarCheckResponseSerializer,
            400: OpenApiResponse(description="Request inválido"),
            404: OpenApiResponse(description="Documento no encontrado"),
            502: OpenApiResponse(description="Error al procesar el texto o el modelo"),
        },
    )
    def post(self, request):
        req = GrammarCheckRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        validated_data = req.validated_data
        
        text_from_input = validated_data.get("text")
        documento_id = validated_data.get("documento_id")
        
        # MEJORA 3: Lógica robusta para manejar archivos desde S3 o cualquier storage.
        if documento_id:
            try:
                doc = Documento.objects.get(pk=documento_id, usuario=request.user)
                # Leemos el contenido del archivo en memoria, sin depender del sistema de archivos.
                file_content = doc.archivo.read()
                # Lo decodificamos a texto.
                text_from_input = file_content.decode('utf-8', errors='ignore')
            except Documento.DoesNotExist:
                return Response({"detail": "Documento no encontrado o no te pertenece."}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = grammar_check_from_text_or_file(
                text=text_from_input,
                idioma=validated_data.get("idioma", "es"),
                max_issues=validated_data.get("max_issues", 200)
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Error al procesar con la IA: {str(e)}"}, status=status.HTTP_502_BAD_GATEWAY)
        
        # CORRECCIÓN 6: Corregimos la clave para acceder al texto corregido.
        response_payload = {
            "issues": result.get("issues", []),
            "counts": result.get("counts", {}),
            "meta": result.get("meta", {}),
            "corrected_text": result.get("corrected_text", ""), # <-- Clave corregida
        }
        return Response(response_payload, status=status.HTTP_200_OK)
    


from .retrieval import search_chunks_strict, search_chunks
from .qa import build_prompt
from rest_framework.permissions import IsAuthenticated

def _s3_presign(key: str, expires=900) -> str | None:
    if not key: 
        return None
    try:
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = "documentos-lexgo-ia-scrapping"
        return s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
        )
    except Exception:
        return None
class AskJurisView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AskJurisRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=AskJurisResponseSerializer,
                description="Respuesta del asistente de jurisprudencia con citas estructuradas.",
            ),
            400: OpenApiResponse(description="Parámetros inválidos"),
            502: OpenApiResponse(description="Error del proveedor LLM"),
        },
        tags=["jurisprudencia"],
        operation_id="ask_juris",
        summary="Consulta asistente de jurisprudencia",
        description="Realiza una consulta sobre jurisprudencia/doctrina/leyes usando RAG y devuelve respuesta y citas.",
    )
    def post(self, request):
        # 1) Validar entrada con el serializer de request
        req_ser = AskJurisRequestSerializer(data=request.data)
        req_ser.is_valid(raise_exception=True)
        data = req_ser.validated_data

        q = data["query"].strip()
        strict = data.get("strict", True)
        debug = data.get("debug", False)
        f = data.get("filters") or {}

        hits = []
        dbg = {}

        # 2) Búsqueda estricta
        if strict:
            r1 = search_chunks_strict(
                q, k=8,
                fuero="Laboral",
                jurisdiccion="Provincia de Buenos Aires",
                tribunal=f.get("tribunal"),
                desde=f.get("desde"),
                hasta=f.get("hasta"),
                min_chars=200,
                min_score=0.82,
                max_per_doc=2,
                debug=debug,
            )
            hits = r1["hits"]
            if debug:
                dbg["strict"] = r1.get("debug")

        # 3) Búsqueda estricta (suave)
        if not hits:
            r2 = search_chunks_strict(
                q, k=8,
                fuero="Laboral",
                jurisdiccion=None,  # soltamos jurisdicción
                tribunal=f.get("tribunal"),
                desde=f.get("desde"),
                hasta=f.get("hasta"),
                min_chars=120,
                min_score=0.75,
                max_per_doc=2,
                debug=debug,
            )
            hits = r2["hits"]
            if debug:
                dbg["strict_soft"] = r2.get("debug")

        # 4) Vector-only
        if not hits:
            hits = search_chunks(q, k=8, fuero=None, jurisdiccion=None, min_chars=80)
            if debug:
                dbg["vector_only"] = {"got_hits": len(hits)}

        # 5) Sin contexto suficiente
        if not hits:
            payload = {
                "query": q,
                "answer": "No encontré contexto suficiente en tu base para responder con citas. Probá con otra formulación o sin filtros.",
                "citations": [],
            }
            if debug:
                payload["debug"] = dbg
            # Serializar salida con el serializer de response (opcional pero prolijo)
            resp_ser = AskJurisResponseSerializer(payload)
            return Response(resp_ser.data, status=status.HTTP_200_OK)

        # 6) Prompt + LLM
        messages = build_prompt(q, hits)
        client = get_openai_client()
        try:
            model = getattr(settings, "OPENAI_MODEL", "gpt-4o")
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=900,
                temperature=0.1,
            )
            answer = resp.choices[0].message.content
        except Exception as e:
            return Response({"detail": f"Error modelo: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        # 7) Armar citas con URL (origen o presign S3)
        citations = []
        for h in hits:
            url = h.get("link_origen") or _s3_presign(h.get("s3_key_document"))
            citations.append({
                "id": f"{h['doc_id']}#{h['chunk_id']}",
                "titulo": h.get("titulo"),
                "tribunal": h.get("tribunal"),
                "fecha": h.get("fecha"),
                "url": url or "",
                "score": float(h.get("score", 0.0)),
            })

        # 8) Serializar respuesta final
        payload = {"query": q, "answer": answer, "citations": citations}
        if debug:
            payload["debug"] = dbg

        resp_ser = AskJurisResponseSerializer(payload)
        return Response(resp_ser.data, status=status.HTTP_200_OK)
    


from datetime import datetime, timezone
def _new_msg_id(prefix: str = "m") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"

def _now_iso_z() -> datetime:
    # DRF lo serializa a ISO; seteo tz UTC para terminar en Z
    return datetime.now(timezone.utc)

def _attachments_to_text(attachments: Optional[List[Dict[str, Any]]]) -> str:
    """
    Extrae texto de adjuntos. Implementá tu lógica real (Textract, PyMuPDF, etc.)
    Dejo un stub seguro.
    """
    if not attachments:
        return ""
    extracted_chunks = []
    for a in attachments:
        try:
            text = extract_text_from_attachment(a)  # <-- implementá esta función en tu proyecto
            if text and text.strip():
                extracted_chunks.append(text.strip())
        except Exception:
            # No rompemos el flujo si un adjunto falla
            continue
    return "\n\n".join(extracted_chunks)

def extract_text_from_attachment(attachment: Dict[str, Any]) -> str:
    """
    Stub. Ejemplos de rutas:
      - si viene 's3_key': descargás con boto3 y extraés
      - si viene 'url': lo traés y extraés
    """
    # TODO: reemplazar por tu extractor real
    return ""

from urllib.parse import urlsplit, urlunsplit

def _canonical_url(raw: str) -> str:
    """
    Normaliza URLs para deduplicar:
    - Pasa a minúsculas el esquema/host.
    - Elimina query y fragment (presigns de S3 cambian por firma).
    """
    if not raw:
        return ""
    p = urlsplit(raw)
    # scheme y netloc en minúsculas; sin query/fragment
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, "", ""))

def _build_unique_citations(hits: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Devuelve [{titulo, url}] únicos, priorizando el primer match.
    Dedup por:
      1) URL canónica (preferente)
      2) Si no hay URL, por doc_id (evita duplicar adjuntos sin URL)
    """
    seen_urls = set()
    seen_docs = set()
    citations: List[Dict[str, str]] = []

    for h in hits:
        raw_url = h.get("link_origen") or _s3_presign(h.get("s3_key_document"))
        titulo = (h.get("titulo") or "Documento").strip()

        if raw_url:
            key = _canonical_url(raw_url)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            citations.append({"titulo": titulo, "url": raw_url})
        else:
            # Sin URL: deduplicar por doc_id para no repetir “Documento adjunto”
            doc_id = h.get("doc_id")
            if not doc_id or doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            # Si no hay URL, no la incluimos (respeta tu contrato de solo titulo+url)
            # Puedes omitir estos sin URL del todo o, si quieres, poner un presign aquí.
            # En tu contrato actual es mejor OMITIRLOS.
            # pass
            # Si prefieres incluirlos igual, comenta el continue y agrega una URL vacía:
            # citations.append({"titulo": titulo, "url": ""})
            continue

    return citations

# ------------------------------- La View -------------------------------------

class AsistenteJurisprudencia(APIView):
    permission_classes = [IsAuthenticated]

    # (Opcional) mantenemos tu extend_schema original si usás drf-spectacular
    # Podés actualizarlo para reflejar el nuevo request/response si querés.

    @extend_schema(
        request=AskJurisRequestUnionSerializer,
        responses={
            200: OpenApiResponse(
                response=ConversationResponseSerializer,
                description="Respuesta del asistente de jurisprudencia con citas estructuradas.",
            ),
            400: OpenApiResponse(description="Parámetros inválidos"),
            502: OpenApiResponse(description="Error del proveedor LLM"),
        },
        tags=["jurisprudencia"],
        operation_id="asistente_jurisprudencia",
        summary="Consulta asistente de jurisprudencia",
        description="Realiza una consulta sobre jurisprudencia/doctrina/leyes usando RAG y devuelve respuesta y citas.",
    )
    def post(self, request):
        # 1) Validar entrada unificada (inicio o continuación)
        ser = AskJurisRequestUnionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        q: str = data["__query__"].strip()
        strict: bool = data.get("strict", True)
        debug: bool = data.get("debug", False)
        f: Dict[str, Any] = data.get("filters") or {}

        is_start = "first_message" in data
        attachments = data.get("attachments") if not is_start else None

        # 2) Construir mensaje del usuario (siempre primer mensaje del array)
        user_msg = {
            "id": _new_msg_id("m"),
            "role": "user",
            "content": q,
            "created_at": _now_iso_z(),
        }

        # 3) Enriquecer el contexto con adjuntos (si los hay)
        attach_text = _attachments_to_text(attachments) if attachments else ""
        pseudo_hits_from_attachments = []
        if attach_text:
            pseudo_hits_from_attachments.append({
                "doc_id": f"attachments::{uuid.uuid4().hex[:8]}",
                "chunk_id": 0,
                "titulo": "Documento adjunto",
                "tribunal": None,
                "fecha": None,
                "link_origen": "",  # si tenés URL pública del adjunto, podés setearla acá
                "s3_key_document": None,
                "score": 1.0,
                "text": attach_text,  # para que tu build_prompt lo pueda usar (si lo soporta)
            })

        hits: List[Dict[str, Any]] = []
        dbg: Dict[str, Any] = {}

        # 4) Búsqueda estricta (PBA/Laboral), como en tu flujo original
        if strict:
            r1 = search_chunks_strict(
                q, k=8,
                fuero="Laboral",
                jurisdiccion="Provincia de Buenos Aires",
                tribunal=f.get("tribunal"),
                desde=f.get("desde"),
                hasta=f.get("hasta"),
                min_chars=200,
                min_score=0.82,
                max_per_doc=2,
                debug=debug,
            )
            hits = r1["hits"]
            if debug:
                dbg["strict"] = r1.get("debug")

        # 5) Búsqueda estricta (suave)
        if not hits:
            r2 = search_chunks_strict(
                q, k=8,
                fuero="Laboral",
                jurisdiccion=None,  # soltamos jurisdicción
                tribunal=f.get("tribunal"),
                desde=f.get("desde"),
                hasta=f.get("hasta"),
                min_chars=120,
                min_score=0.75,
                max_per_doc=2,
                debug=debug,
            )
            hits = r2["hits"]
            if debug:
                dbg["strict_soft"] = r2.get("debug")

        # 6) Vector-only
        if not hits:
            hits = search_chunks(q, k=8, fuero=None, jurisdiccion=None, min_chars=80)
            if debug:
                dbg["vector_only"] = {"got_hits": len(hits)}

        # 7) Añadimos pseudo-hits de adjuntos al final (sin desplazar citas reales)
        if pseudo_hits_from_attachments:
            hits = hits + pseudo_hits_from_attachments

        # 8) Sin contexto suficiente → respondemos igual en el formato requerido
        if not hits:
            assistant_content = (
                "No encontré contexto suficiente en tu base para responder con citas. Probá con otra "
                "formulación o sin filtros."
            )
            assistant_msg = {
                "id": _new_msg_id("m"),
                "role": "assistant",
                "content": assistant_content,
                "created_at": _now_iso_z(),
                "citations": [],  # cumple el formato exigido
            }
            resp_payload = {"messages": [user_msg, assistant_msg]}
            out_ser = ConversationResponseSerializer(resp_payload)
            return Response(out_ser.data, status=status.HTTP_200_OK)

        # 9) Prompt + LLM
        try:
            messages = build_prompt(q, hits)
            client = get_openai_client()
            model = getattr(settings, "OPENAI_MODEL", "gpt-4o")
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=900,
                temperature=0.1,
            )
            answer = resp.choices[0].message.content
        except Exception as e:
            # Si el proveedor falla, devolvemos igual dos mensajes (user+assistant con error)
            assistant_msg = {
                "id": _new_msg_id("m"),
                "role": "assistant",
                "content": f"Error del proveedor LLM: {e}",
                "created_at": _now_iso_z(),
                "citations": [],
            }
            resp_payload = {"messages": [user_msg, assistant_msg]}
            out_ser = ConversationResponseSerializer(resp_payload)
            return Response(out_ser.data, status=status.HTTP_502_BAD_GATEWAY)

        # 10) Citas únicas en el formato requerido (solo titulo + url)
        citations = _build_unique_citations(hits)

        assistant_msg = {
            "id": _new_msg_id("m"),
            "role": "assistant",
            "content": answer,
            "created_at": _now_iso_z(),
            "citations": citations,
        }

        resp_payload = {"messages": [user_msg, assistant_msg]}
        out_ser = ConversationResponseSerializer(resp_payload)
        return Response(out_ser.data, status=status.HTTP_200_OK)



def run_assistant_reply(conversation, user_message: str) -> str:
    """
    Ejecuta la respuesta del asistente jurídico usando búsqueda estricta y LLM.
    - Usa solo search_chunks_strict (sin relajado).
    - Arma el prompt contextual con hits relevantes.
    - Devuelve solo el texto final (sin TL;DR, sin IDs ni bloque de citas).
    """
    # 1) Búsqueda estricta (igual que en AskJuris 'strict')
    r = search_chunks_strict(
        user_message,
        k=8,
        fuero="Laboral",
        jurisdiccion="Provincia de Buenos Aires",
        tribunal=None,
        desde=None,
        hasta=None,
        min_chars=200,
        min_score=0.82,
        max_per_doc=2,
        debug=False,
    )
    hits = r.get("hits", [])

    # Si no hay contexto, devolvemos un mensaje claro
    if not hits:
        return (
            "No encontré contexto suficiente en la base de jurisprudencia para responder tu consulta. "
            "Podés intentar reformular la pregunta o ampliar el criterio de búsqueda."
        )

    # 2) Construcción del prompt
    user_query = user_message.strip()
    context = "\n\n".join(
        f"[{h['doc_id']}#{h['chunk_id']}] {h['text']}" for h in hits
    )

    user_prompt = (
        f"Consulta del usuario:\n{user_query}\n\n"
        "Fragmentos relevantes de jurisprudencia, leyes y doctrina "
        "(si necesitás, podés referenciar la URL asociada al ID entre [ ] en el texto):\n"
        f"{context}\n\n"
        "Instrucciones de redacción:\n"
        "- Redactá una respuesta clara, formal y concisa, con tono de análisis jurídico.\n"
        "- No incluyas la etiqueta 'TL;DR' ni encabezados numéricos.\n"
        "- Si el contexto es insuficiente, indicá explícitamente que no se encontraron antecedentes o conclusiones suficientes y por qué.\n"
        "- No enumeres ni transcribas las citas al final: esas se devuelven por separado.\n"
        "- Si mencionás una fuente, usá su URL (no el ID) solo cuando aporte valor.\n\n"
        "Formato esperado: párrafos con análisis y conclusiones, sin listas ni encabezados."
    )

    messages = build_prompt(user_query, hits)  # tu helper existente
    messages.append({"role": "user", "content": user_prompt})

    # 3) Llamada al LLM
    try:
        model = getattr(settings, "OPENAI_MODEL", "gpt-4o")
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=900,
            temperature=0.1,
        )
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Ocurrió un error al generar la respuesta: {e}"

    # 4) Limpieza final (por si el modelo dejó IDs o etiquetas)
    import re
    answer_clean = re.sub(r"\[[a-f0-9]{6,}#[0-9]+\]", "", answer)               # quita IDs [doc#chunk]
    answer_clean = re.sub(r"(?i)\bTL;DR:?|\bCitas:?|\bReferencias:?", "", answer_clean)
    answer_clean = re.sub(r"\n{3,}", "\n\n", answer_clean).strip()

    return answer_clean



# --------------------------------------
# 2) Obtener una conversación (con msgs)
# --------------------------------------
class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationDetailSerializer

    @extend_schema(
        responses={200: ConversationDetailSerializer},
        operation_id="conversation_detail",
        summary="Obtener una conversación (con mensajes)",
        tags=["conversaciones"],
    )
    def get(self, request, conversation_id: str):
        conv = get_object_or_404(Conversation, pk=conversation_id, user=request.user)
        # Assumimos related_name="messages" y ordering por created_at en el modelo o en el serializer
        data = ConversationDetailSerializer(conv).data
        return Response(data, status=status.HTTP_200_OK)

# --------------------------
# 4) Crear nueva conversación
# --------------------------
@extend_schema_view(
    get=extend_schema(
        responses={200: ConversationListItemSerializer(many=True)},
        operation_id="conversations_list",
        summary="Listar conversaciones (sin mensajes)",
        tags=["conversaciones"],
    ),
    post=extend_schema(
        request=ConversationCreateRequestSerializer,
        responses={201: ConversationDetailSerializer},
        operation_id="conversations_create",
        summary="Crear conversación",
        tags=["conversaciones"],
    ),
)
class ConversationsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationListItemSerializer  # ayuda al schema

    # GET /api/conversations  -> lista (sin messages)
    def get(self, request):
        qs = (
            Conversation.objects
            .filter(user=request.user)     # si tu modelo tiene user
            .order_by("-updated_at")
        )
        data = ConversationListItemSerializer(qs, many=True).data
        return Response({"items": data}, status=status.HTTP_200_OK)

    # POST /api/conversations  -> crea y devuelve CON mensajes
    @transaction.atomic
    def post(self, request):
        ser = ConversationCreateRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        first_message = ser.validated_data["first_message"].strip()
        title = ser.validated_data.get("title") or first_message[:60]

        now = timezone.now()
        conv = Conversation.objects.create(
            user=request.user,
            title=title,
            created_at=now, updated_at=now, last_message_at=now,
        )

        # mensaje del usuario
        user_msg = Message.objects.create(
            conversation=conv, role="user", content=first_message, created_at=now
        )

        # respuesta IA
        answer = run_assistant_reply(conv, first_message)
        asst_msg = Message.objects.create(
            conversation=conv, role="assistant", content=answer, created_at=timezone.now()
        )

        conv.updated_at = timezone.now()
        conv.last_message_at = asst_msg.created_at
        conv.save(update_fields=["updated_at", "last_message_at"])

        detail = ConversationDetailSerializer(conv).data
        return Response(detail, status=status.HTTP_201_CREATED)

# ----------------------------------------------------
# 3) Enviar mensaje y devolver SOLO los nuevos mensajes
# ----------------------------------------------------
class ConversationMessageCreateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationMessageCreateResponseSerializer

    @extend_schema(
        request=ConversationMessageCreateRequestSerializer,
        responses={200: ConversationMessageCreateResponseSerializer},
        operation_id="conversation_post_message",
        summary="Enviar mensaje y recibir delta",
        tags=["conversaciones"],
    )
    @transaction.atomic
    def post(self, request, conversation_id: str):
        conv = get_object_or_404(Conversation, pk=conversation_id, user=request.user)  
        ser = ConversationMessageCreateRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        content = ser.validated_data["content"].strip()
        idem_key = ser.validated_data.get("idempotency_key") or ""

        # Idempotencia: si ya procesamos este key, devolvemos lo que generamos
        if idem_key:
            existing = IdempotencyKey.objects.filter(
                user=request.user,
                key=idem_key,
                target=f"conv:{conv.id}"
            ).first()
            if existing:
                # ya existe: devolvemos exactamente lo que se respondió la 1ª vez
                # guardaste los IDs de mensajes en existing.meta? (opcional)
                # Si no, devolvé 409 o reintenta con otra clave
                return Response(
                    {"messages": existing.get_messages_payload()},
                    status=status.HTTP_200_OK
                )

        now = timezone.now()

        # 1) crear mensaje del usuario
        user_msg = Message.objects.create(
            conversation=conv,
            role="user",
            content=content,
            created_at=now,
        )

        # 2) generar respuesta IA
        answer = run_assistant_reply(conv, content)
        asst_msg = Message.objects.create(
            conversation=conv,
            role="assistant",
            content=answer,
            created_at=timezone.now(),
        )

        # 3) actualizar conv
        conv.updated_at = timezone.now()
        conv.last_message_at = asst_msg.created_at
        conv.save(update_fields=["updated_at", "last_message_at"])

        # 4) persistir idempotency
        if idem_key:
            # guardamos los mensajes para reuso futuro
            # asumimos que IdempotencyKey tiene un JSONField `payload` o método helper.
            IdempotencyKey.objects.create(
                user=request.user,
                key=idem_key,
                target=f"conv:{conv.id}",
                payload={
                    "messages": [
                        {
                            "id": str(user_msg.id),
                            "role": user_msg.role,
                            "content": user_msg.content,
                            "created_at": user_msg.created_at.isoformat().replace("+00:00", "Z"),
                        },
                        {
                            "id": str(asst_msg.id),
                            "role": asst_msg.role,
                            "content": asst_msg.content,
                            "created_at": asst_msg.created_at.isoformat().replace("+00:00", "Z"),
                        },
                    ]
                }
            )

        # 5) respuesta (SOLO mensajes nuevos)
        resp_ser = ConversationMessageCreateResponseSerializer(
            {"messages": [
                {
                    "id": user_msg.id,
                    "role": user_msg.role,
                    "content": user_msg.content,
                    "created_at": user_msg.created_at,
                },
                {
                    "id": asst_msg.id,
                    "role": asst_msg.role,
                    "content": asst_msg.content,
                    "created_at": asst_msg.created_at,
                },
            ]}
        )
        return Response(resp_ser.data, status=status.HTTP_200_OK)