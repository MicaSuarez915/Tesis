from django.shortcuts import render

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
    list=extend_schema(
        operation_id="ia_summaries_list",
        summary="Listar resúmenes",
        description="Lista todos los resúmenes generados por el usuario autenticado.",
        tags=["IA"],
        responses={200: SummaryRunSerializer},
    ),
    retrieve=extend_schema(
        operation_id="ia_summaries_retrieve",
        summary="Obtener un resumen",
        tags=["IA"],
        responses={200: SummaryRunSerializer, 404: OpenApiResponse(description="No encontrado")},
    ),
    destroy=extend_schema(
        operation_id="ia_summaries_delete",
        summary="Eliminar un resumen",
        tags=["IA"],
        responses={204: OpenApiResponse(description="Eliminado"), 404: OpenApiResponse(description="No encontrado")},
    ),
    # create/update/partial_update los podés dejar sin exponer si no los usás
)
class SummaryRunViewSet(viewsets.ModelViewSet):
    """
    CRUD + acción `generate` para crear un resumen y verificarlo en un paso.
    """
    queryset = SummaryRun.objects.select_related("created_by").all()
    serializer_class = SummaryRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        # Si querés que cada usuario vea SOLO lo suyo, descomenta:
        return qs.filter(created_by=self.request.user)
        return qs

    @extend_schema(
        operation_id="ia_summaries_generate",
        summary="Generar un resumen y verificarlo",
        description=(
            "Genera un resumen ejecutivo (usando la DB como contexto) y lo verifica con otro modelo. "
            "Devuelve el SummaryRun persistido con su VerificationResult embebido."
        ),
        tags=["IA"],
        request=SummaryGenerateSerializer,
        responses={
            201: SummaryRunSerializer,
            400: OpenApiResponse(description="Request inválido"),
            401: OpenApiResponse(description="No autenticado"),
            502: OpenApiResponse(description="Error al generar/verificar"),
        },
        examples=[GEN_REQ_EXAMPLE, GEN_RES_EXAMPLE],
    )
    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """
        POST /api/ia/summaries/generate
        body:
        {
          "topic": "Resumen mensual",
          "filters": {"estado":"en_tramite","jurisdiccion":"CABA","desde":"2025-08-01"}
        }
        """
        payload = SummaryGenerateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        topic = payload.validated_data["topic"]
        filters = payload.validated_data.get("filters", {})

        try:
            db_json, summary_text, verdict, issues, raw_verifier = run_summary_and_verification(topic, filters)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        run = SummaryRun.objects.create(
            topic=topic,
            filters=filters,
            db_snapshot=db_json,
            prompt="(generado internamente en ia.services)",
            summary_text=summary_text,
            citations=[],                     # si luego agregás RAG, podés guardar citas aquí
            created_by=request.user if request.user.is_authenticated else None,
        )
        VerificationResult.objects.create(
            summary_run=run,
            verdict=verdict,
            issues=issues,
            raw_output=raw_verifier
        )

        return Response(SummaryRunSerializer(run).data, status=status.HTTP_201_CREATED)


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