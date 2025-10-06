from time import timezone
from django.shortcuts import render, get_object_or_404

# Create your views here.
    
import openai
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import viewsets
from rest_framework import permissions
from rest_framework.generics import GenericAPIView
from django.conf import settings


from openai import OpenAI

openai.api_key = settings.OPENAI_API_KEY

client = OpenAI(
  api_key=settings.OPENAI_API_KEY
)

from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SummaryRun, VerificationResult 
from causa.models import Causa
from causa.models import Documento
from .serializers import SummaryRunSerializer, SummaryGenerateSerializer, VerificationResultSerializer, GrammarCheckResponseSerializer, GrammarCheckRequestSerializer

# Importa el orquestador que ya definimos antes (GPT u Ollama)
# Debe existir en ia/services.py: run_summary_and_verification(topic, filters) -> (db_json, summary_text, verdict, issues, raw_json_text)
from .services import run_summary_and_verification, run_case_summary_and_verification

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, extend_schema_view, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from django.db import transaction

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
        return super().get_queryset().filter(created_by=self.request.user)

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
    @action(detail=False, methods=["get"], url_path=r"by-causa/(?P<causa_id>\d+)")
    def get_by_causa(self, request, causa_id: str):
        user = request.user
        causa = get_object_or_404(Causa.objects.filter(creado_por=user), pk=int(causa_id))
        run = (SummaryRun.objects
               .filter(causa=causa, created_by=user)
               .order_by("-updated_at", "-created_at")
               .first())
        if not run:
            return Response({"detail": "No existe un resumen para esta causa."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(SummaryRunSerializer(run).data, status=status.HTTP_200_OK)

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
    @action(detail=False, methods=["post"], url_path=r"by-causa/(?P<causa_id>\d+)/create")
    def create_by_causa(self, request, causa_id: str):
        user = request.user
        causa = get_object_or_404(Causa.objects.filter(creado_por=user), pk=int(causa_id))

        payload = SummaryGenerateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        topic = payload.validated_data["topic"]
        filters = payload.validated_data.get("filters", {}) or {}
        effective_filters = {"causa_id": causa.id, **filters}

        try:
            with transaction.atomic():
                exists = SummaryRun.objects.filter(causa=causa, created_by=user).exists()
                if exists:
                    return Response(
                        {"detail": "Ya existe un resumen para esta causa. Use PUT /update para actualizar."},
                        status=status.HTTP_409_CONFLICT,
                    )

                db_json, summary_text, verdict, issues, raw_verifier = \
                    run_summary_and_verification(topic, effective_filters)

                run = SummaryRun.objects.create(
                    topic=topic,
                    causa=causa,
                    filters=effective_filters,
                    db_snapshot=db_json,
                    prompt="(generado en POST /create)",
                    summary_text=summary_text,
                    citations=[],
                    created_by=user,
                )
                try:
                    VerificationResult.objects.create(
                        summary_run=run, verdict=verdict, issues=issues, raw_output=raw_verifier
                    )
                except Exception:
                    pass

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
    @action(detail=False, methods=["put"], url_path=r"by-causa/(?P<causa_id>\d+)/update")
    def update_by_causa(self, request, causa_id: str):
        user = request.user
        causa = get_object_or_404(Causa.objects.filter(creado_por=user), pk=int(causa_id))

        # Body opcional: si no envían nada, reusamos topic/filters existentes
        if request.data:
            payload = SummaryGenerateSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            topic_in = payload.validated_data["topic"]
            filters_in = payload.validated_data.get("filters", {}) or {}
        else:
            topic_in = None
            filters_in = None

        try:
            with transaction.atomic():
                run = (SummaryRun.objects
                       .select_for_update()
                       .filter(causa=causa, created_by=user)
                       .order_by("-updated_at", "-created_at")
                       .first())
                if not run:
                    return Response(
                        {"detail": "No existe un resumen para esta causa. Use POST /create para crearlo."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                topic = topic_in or (run.topic or f"Resumen de causa {causa.numero_expediente or causa.id}")
                filters_base = run.filters if isinstance(run.filters, dict) else {}
                effective_filters = {"causa_id": causa.id, **(filters_in or filters_base)}

                db_json, summary_text, verdict, issues, raw_verifier = \
                    run_summary_and_verification(topic, effective_filters)

                # Actualización (PUT)
                run.topic = topic
                run.filters = effective_filters
                run.db_snapshot = db_json
                run.summary_text = summary_text
                run.save(update_fields=["topic", "filters", "db_snapshot", "summary_text", "created_at", "updated_at"])

                try:
                    vr = getattr(run, "verificationresult", None)
                    if vr:
                        vr.verdict = verdict
                        vr.issues = issues
                        vr.raw_output = raw_verifier
                        vr.save(update_fields=["verdict", "issues", "raw_output"])
                    else:
                        VerificationResult.objects.create(
                            summary_run=run, verdict=verdict, issues=issues, raw_output=raw_verifier
                        )
                except Exception:
                    pass

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
        try:
            run = SummaryRun.objects.get(pk=pk)
        except SummaryRun.DoesNotExist:
            return Response({"detail": "SummaryRun no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        # Re-usa el snapshot y el summary que ya existen
        from .services import build_verifier_prompt, chat  # si tu services expone estas utilidades
        try:
            verifier_prompt = build_verifier_prompt(run.summary_text, run.db_snapshot)
            # Usa tu cliente por defecto (gpt-4o-mini, etc.)
            verifier_json_text = chat(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un verificador estricto de factualidad y coherencia."},
                    {"role": "user", "content": verifier_prompt}
                ],
                max_tokens=600,
                response_format={"type": "json_object"},
                temperature=0.0
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        import json
        verdict, issues = "warning", []
        try:
            parsed = json.loads(verifier_json_text)
            verdict = parsed.get("veredicto", verdict)
            issues = parsed.get("issues", [])
        except Exception:
            issues = [{"tipo": "parser_error", "detalle": "El verificador no devolvió JSON válido", "raw": verifier_json_text[:800]}]

        # upsert
        VerificationResult.objects.update_or_create(
            summary_run=run,
            defaults={"verdict": verdict, "issues": issues, "raw_output": verifier_json_text}
        )

        return Response(VerificationResultSerializer(run.verification).data, status=status.HTTP_200_OK)


class CaseSummaryView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SummaryRunSerializer  # <- para que drf-spectacular tenga un serializer base

    @extend_schema(
        operation_id="ia_case_summary_create",
        description="Genera y persiste un resumen verificado de la causa indicada.",
        parameters=[
            OpenApiParameter(
                name="causa_id",
                type=int,
                location=OpenApiParameter.PATH,
                description="ID de la causa"
            )
        ],
        request=None,  # no se envía body en este POST
        responses={
            201: SummaryRunSerializer,
            404: OpenApiResponse(description="Causa no encontrada"),
            502: OpenApiResponse(description="Error al generar el resumen"),
        },
        tags=["IA"],
    )
    def post(self, request, causa_id: int):
        try:
            causa = Causa.objects.get(pk=causa_id)
        except Causa.DoesNotExist:
            return Response({"detail": "Causa no encontrada"}, status=status.HTTP_404_NOT_FOUND)

        try:
            ctx, summary, verdict, issues, raw = run_case_summary_and_verification(causa.id)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        run = SummaryRun.objects.create(
            topic=f"Resumen de causa #{causa.id}",
            causa=causa,
            filters={"causa_id": causa.id},
            db_snapshot=ctx,
            prompt="(generado internamente en ia.services)",
            summary_text=summary,
            created_by=request.user,
        )
        VerificationResult.objects.create(
            summary_run=run,
            verdict=verdict,
            issues=issues,
            raw_output=raw,
        )
        return Response(SummaryRunSerializer(run).data, status=status.HTTP_201_CREATED)
    


from .services_grammar import grammar_check_from_text_or_file

class GrammarCheckView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GrammarCheckResponseSerializer  # para spectacular

    @extend_schema(
        operation_id="ia_grammar_check",
        tags=["IA"],
        summary="Chequeo de gramática y ortografía (texto o documento)",
        request=GrammarCheckRequestSerializer,
        responses={200: GrammarCheckResponseSerializer, 400: OpenApiResponse(description="Request inválido")}
    )
    def post(self, request):
        req = GrammarCheckRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        text = req.validated_data.get("text")
        documento_id = req.validated_data.get("documento_id")
        idioma = req.validated_data.get("idioma", "es")
        max_issues = req.validated_data.get("max_issues", 200)

        file_path = None
        if documento_id:
            try:
                doc = Documento.objects.get(pk=documento_id)
            except Documento.DoesNotExist:
                return Response({"detail": "Documento no encontrado"}, status=status.HTTP_404_NOT_FOUND)
            # Para FileField, en almacenamiento local:
            if hasattr(doc.archivo, "path"):
                file_path = doc.archivo.path
            else:
                return Response({"detail": "El backend de storage no permite path local. Descargá el archivo primero."},
                                status=status.HTTP_400_BAD_REQUEST)

        try:
            result = grammar_check_from_text_or_file(
                text=text, file_path=file_path, idioma=idioma, max_issues=max_issues
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_200_OK)