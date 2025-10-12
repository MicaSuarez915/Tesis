
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
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SummaryRun, VerificationResult 
from causa.models import Causa
from causa.models import Documento
from .serializers import SummaryRunSerializer, SummaryGenerateSerializer, VerificationResultSerializer, GrammarCheckResponseSerializer, GrammarCheckRequestSerializer
from django.utils import timezone

# Importa el orquestador que ya definimos antes (GPT u Ollama)
# Debe existir en ia/services.py: run_summary_and_verification(topic, filters) -> (db_json, summary_text, verdict, issues, raw_json_text)
from .services import run_summary_and_verification, run_case_summary_and_verification

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, extend_schema_view, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from django.db import transaction
from django.db.models.functions import Coalesce

from openai import OpenAI

openai.api_key = settings.OPENAI_API_KEY

client = OpenAI(
  api_key=settings.OPENAI_API_KEY
)



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
        """
        POST /api/ia/grammar-check
        Permite enviar texto directo o el ID de un documento existente.
        Retorna errores detectados y texto completamente corregido.
        """
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
                return Response(
                    {"detail": "Documento no encontrado."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Para FileField en almacenamiento local:
            if hasattr(doc.archivo, "path"):
                file_path = doc.archivo.path
            else:
                return Response(
                    {
                        "detail": (
                            "El backend de storage no permite obtener un path local. "
                            "Debes descargar el archivo primero o usar un texto plano."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            result = grammar_check_from_text_or_file(
                text=text, file_path=file_path, idioma=idioma, max_issues=max_issues
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


        response_payload = {
            "issues": result.get("issues", []),
            "counts": result.get("counts", {}),
            "meta": result.get("meta", {}),
            "corrected_text": result.get("corrected", {}).get("text", ""),  # <- texto completo corregido
            "corrected_pages": result.get("corrected", {}).get("pages", []),  # <- líneas por página
        }

        return Response(response_payload, status=status.HTTP_200_OK)