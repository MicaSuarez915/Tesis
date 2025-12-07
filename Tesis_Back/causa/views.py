import json
from django.shortcuts import render

# Create your views here.
import openai
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django_filters import rest_framework as dj_filters
from django.utils import timezone
from datetime import timedelta, date

from .models import *
from .serializers import *
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes, OpenApiExample, OpenApiResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework import parsers
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework_simplejwt.authentication import JWTAuthentication
from django_filters.rest_framework import DjangoFilterBackend
import unicodedata
import os
import re
import uuid
import boto3
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from openai import OpenAI

# Para desarrollo, permitimos acceso sin token:
ALLOW = [permissions.AllowAny]

# Para producción, solo permitimos acceso con token:
RESTRICTED_ALLOW = [permissions.IsAuthenticated]

# ---------- FilterSets ----------
class CausaFilter(dj_filters.FilterSet):
    # Rango de fechas de inicio: ?fecha_inicio_after=2025-01-01&fecha_inicio_before=2025-12-31
    fecha_inicio_after = dj_filters.DateFilter(field_name="fecha_inicio", lookup_expr="gte")
    fecha_inicio_before = dj_filters.DateFilter(field_name="fecha_inicio", lookup_expr="lte")

    class Meta:
        model = Causa
        fields = {
            "numero_expediente": ["exact", "icontains"],
            "fuero": ["exact", "icontains"],
            "jurisdiccion": ["exact", "icontains"],
            "estado": ["exact", "icontains"],
            "creado_por": ["exact"],
        }

class EventoFilter(dj_filters.FilterSet):
    fecha_after = dj_filters.DateFilter(field_name="fecha", lookup_expr="gte")
    fecha_before = dj_filters.DateFilter(field_name="fecha", lookup_expr="lte")
    plazo_after = dj_filters.DateFilter(field_name="plazo_limite", lookup_expr="gte")
    plazo_before = dj_filters.DateFilter(field_name="plazo_limite", lookup_expr="lte")
    causa = dj_filters.NumberFilter(field_name="causa_id", lookup_expr="exact")

    class Meta:
        model = EventoProcesal
        fields = ["causa"]


def _safe_all(obj, attr_name, fallback_attr=None):
    mgr = getattr(obj, attr_name, None)
    if mgr is None and fallback_attr:
        mgr = getattr(obj, fallback_attr, None)
    return mgr.all() if mgr is not None else []

# ---- grafo builder ---- ARREGLAR ESTA PARTE
@extend_schema(
    summary="Grafo de una causa",
    description="Obtiene, reemplaza o borra el JSON del grafo. Acepta `{nodes:[], edges:[]}` o `{data:{...}}`.",
    tags=["Causas", "Grafo"],
)
@action(detail=True, methods=["get", "put", "delete"], url_path="grafo",
        permission_classes=[permissions.IsAuthenticated])
def grafo(self, request, pk=None):
    causa = self.get_object()

    # si no existe, crear con data vacía (sin defaults raros)
    grafo_obj, _ = CausaGrafo.objects.get_or_create(causa=causa, defaults={"data": {}})

    if request.method == "GET":
        return Response(grafo_obj.data or {}, status=status.HTTP_200_OK)

    if request.method == "PUT":
        payload = request.data

        # Acepta JSON plano {nodes, edges}
        if isinstance(payload, dict) and "nodes" in payload and "edges" in payload:
            grafo_obj.data = payload
            grafo_obj.save(update_fields=["data", "actualizado_en"])
            return Response(grafo_obj.data, status=status.HTTP_200_OK)

        # Acepta { "data": {nodes, edges} }
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            data_obj = payload["data"]
            if "nodes" in data_obj and "edges" in data_obj:
                grafo_obj.data = data_obj
                grafo_obj.save(update_fields=["data", "actualizado_en"])
                return Response(grafo_obj.data, status=status.HTTP_200_OK)

        return Response(
            {"detail": "Formato inválido. Enviá `{nodes:[], edges:[]}` o `{data:{nodes:[], edges:[]}}`."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # DELETE → limpiar
    grafo_obj.data = {}
    grafo_obj.save(update_fields=["data", "actualizado_en"])
    return Response(status=status.HTTP_204_NO_CONTENT)



# ---------- ViewSets con filtrado / búsqueda / orden ----------
@extend_schema_view(
    list=extend_schema(
        summary="Listar causas",
        description="Lista paginada de causas con filtros, búsqueda y orden.",
    ),
    retrieve=extend_schema(
        summary="Ver una causa",
        description="Recupera una causa por ID.",
    ),
    create=extend_schema(
        summary="Crear causa",
        description="Crea una nueva causa.",
    ),
    update=extend_schema(
        summary="Actualizar causa (PUT)",
        description="Reemplaza completamente la causa.",
    ),
    partial_update=extend_schema(
        summary="Actualizar causa (PATCH)",
        description="Actualiza parcialmente la causa.",
    ),
    destroy=extend_schema(
        summary="Eliminar causa",
        description="Elimina una causa por ID.",
    ),
)
@extend_schema(tags=["Causas"])
class CausaViewSet(viewsets.ModelViewSet):
    queryset = Causa.objects.all().order_by("-id")
    serializer_class = CausaSerializer
    permission_classes = ALLOW
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]

    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CausaFilter
    search_fields = ["numero_expediente", "caratula", "fuero", "jurisdiccion", "estado"]
    ordering_fields = ["fecha_inicio", "creado_en", "actualizado_en", "numero_expediente"]

    def get_serializer_class(self):
        """
        Elige un serializador basado en la acción.
        - Para la lista de causas, usa CausaVariasSerializer.
        - Para todo lo demás (ver, crear, editar), usa CausaSerializer.
        """
        if self.action == 'list':
            return CausaVariasSerializer
        return CausaSerializer

    def get_queryset(self):
        if not self.request.user or self.request.user.is_anonymous:
            return Causa.objects.none()
        # Sólo causas creadas por el usuario autenticado
        return Causa.objects.filter(creado_por=self.request.user).order_by("-id")

    def perform_create(self, serializer):
        # Seteá el dueño automáticamente
        serializer.save(creado_por=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        """
        Obtiene los datos de una causa y añade sus 10 documentos más recientes.
        """
        # 1. Obtiene los datos de la causa usando el CausaSerializer
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        causa_data = serializer.data

        # 2. Busca y serializa los 10 documentos más recientes
        documentos_recientes_qs = instance.documentos.all().order_by('-creado_en')[:10]
        documentos_serializer = DocumentoSerializer(documentos_recientes_qs, many=True)

        # 3. Añade los documentos a la respuesta
        causa_data['documentos'] = documentos_serializer.data

        return Response(causa_data)


    @extend_schema(
        summary="Timeline de una causa",
        description="Línea de tiempo de la causa, ordenada por fecha, con filtros opcionales y opción de incluir documentos.",
        parameters=[
            OpenApiParameter("desde", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="YYYY-MM-DD"),
            OpenApiParameter("hasta", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="YYYY-MM-DD"),
            OpenApiParameter("con_documentos", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="1/true para incluir documentos"),
        ],
        responses={200: TimelineResponseSerializer},
    )
    @action(detail=True, methods=["get"], url_path="timeline")
    def timeline(self, request, pk=None):
        causa = self.get_object()
        desde = request.query_params.get("desde")
        hasta = request.query_params.get("hasta")

        qs = causa.eventos.all().order_by("fecha", "id")
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)

        data = EventoProcesalSerializer(qs, many=True).data

        if request.query_params.get("con_documentos") in {"1", "true", "True"}:
            documentos = DocumentoSerializer(causa.documentos.order_by("-fecha", "-id"), many=True).data
            return Response({"causa": causa.id, "eventos": data, "documentos": documentos})

        return Response({"causa": causa.id, "eventos": data})

    # /api/causas/{pk}/proximos/?dias=14&solo_con_plazo=1&desde_hoy=1
    @extend_schema(
        summary="Próximos eventos de una causa",
        description="Eventos próximos de la causa (por fecha o plazo_limite).",
        parameters=[
            OpenApiParameter("dias", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Días hacia adelante (default 14)"),
            OpenApiParameter("solo_con_plazo", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="1/true para solo eventos con plazo"),
            OpenApiParameter("desde_hoy", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="1/true para empezar en hoy (si no, desde ayer)"),
        ],
        responses={200: ProximosResponseSerializer},
    )
    @action(detail=True, methods=["get"], url_path="proximos")
    def proximos(self, request, pk=None):
        causa = self.get_object()
        try:
            dias = int(request.query_params.get("dias", 14))
        except ValueError:
            dias = 14

        hoy = date.today()
        desde = hoy if request.query_params.get("desde_hoy") in {"1", "true", "True"} else (hoy - timedelta(days=1))
        hasta = hoy + timedelta(days=dias)

        qs = EventoProcesal.objects.filter(causa=causa).filter(
            models.Q(fecha__range=(desde, hasta)) |
            models.Q(plazo_limite__range=(desde, hasta))
        )
        if request.query_params.get("solo_con_plazo") in {"1", "true", "True"}:
            qs = qs.filter(plazo_limite__isnull=False)

        data = EventoProcesalSerializer(qs.order_by("plazo_limite", "fecha", "id"), many=True).data
        return Response({"desde": desde, "hasta": hasta, "eventos": data})


    @extend_schema(
        description="Obtiene o reemplaza el JSON del grafo para esta causa.",
        responses={200: CausaGrafoSerializer},
        tags=["Causas", "Grafo"],
    )
    @action(detail=True, methods=["get", "put", "delete"], url_path="grafo", permission_classes=[permissions.IsAuthenticated])
    def grafo(self, request, pk=None):
        causa = self.get_object()

        # Ensure existe entry de grafo (o generarlo si falta)
        grafo_obj, created = CausaGrafo.objects.get_or_create(causa=causa)
        if created or not grafo_obj.data:
            grafo_obj.data = grafo(causa)
            grafo_obj.save(update_fields=["data", "actualizado_en"])

        if request.method == "GET":
            return Response(CausaGrafoSerializer(grafo_obj).data)

        if request.method == "PUT":
            # reemplazo total del JSON
            serializer = CausaGrafoSerializer(grafo_obj, data=request.data, partial=False)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        if request.method == "DELETE":
            #Opción B (si preferís limpiarlo del todo):
            grafo_obj.data = {}
            grafo_obj.save(update_fields=["data", "actualizado_en"])
            return Response(status=status.HTTP_204_NO_CONTENT)
    
    # Crear causa + partes + profesionales + documentos + eventos + grafo en una sola llamada

    parser_classes = (JSONParser, MultiPartParser, FormParser)

    @extend_schema(
        summary="Crear causa completa (nested)",
        description=(
            "Crea una causa y **todos** sus vínculos (partes, profesionales, documentos, eventos y grafo) "
            "en una sola llamada. Hace *upsert* de Parte/Profesional/RolParte si vienen por atributos. "
            "Idempotencia opcional por triple-clave (numero_expediente+fuero+jurisdiccion+creado_por) y `idempotency_key`."
        ),
        request=CausaFullCreateSerializer,
        responses={201: CausaSerializer, 200: CausaSerializer},
        examples=[
            OpenApiExample(
                "Payload mínimo y completo",
                value={
                        "idempotency_key": "gpt-run-2025-10-05-lexgo-001",
                        "numero_expediente": "EXP-8457/2025",
                        "caratula": "Pérez, Juan c/ Acme S.A. s/ Despido",
                        "fuero": "Laboral",
                        "jurisdiccion": "CABA",
                        "fecha_inicio": "2025-09-09",
                        "estado": "abierta",
                        "creado_por": 2,
                        "partes": [
                            {
                            "parte": {
                                "tipo_persona": "F",
                                "nombre_razon_social": "Juan Pérez",
                                "documento": "30.111.222",
                                "email": "juan.perez@mail.com",
                                "telefono": "+54 9 11 5555-0001",
                                "domicilio": "calle 1234"
                            }
                            },
                            {
                            "parte": {
                                "tipo_persona": "J",
                                "nombre_razon_social": "Acme S.A.",
                                "cuit_cuil": "30-12345678-9",
                                "email": "legales@acme.com.ar",
                                "domicilio": "calle 1234"
                            }
                            },
                            {
                            "parte": {
                                "tipo_persona": "F",
                                "nombre_razon_social": "María Gómez",
                                "documento": "27.998.776",
                                "email": "maria.gomez@lopezasoc.com",
                                "domicilio": "calle 1234"
                            }
                            },
                            {
                            "parte": {
                                "tipo_persona": "F",
                                "nombre_razon_social": "Lucía Fernández",
                                "documento": "36.554.321",
                                "email": "lucia.fernandez@estudio-perez.com",
                                "domicilio":"calle 1234"
                            }
                            },
                            {
                            "parte": {
                                "tipo_persona": "F",
                                "nombre_razon_social": "Carlos Ruiz",
                                "documento": "28.445.112",
                                "email": "carlos.ruiz@mail.com"
                            }
                            }
                        ],

                        "eventos": [
                            {
                            "id": "E1",
                            "titulo": "Hecho generador",
                            "descripcion": "Despido directo comunicado por Acme S.A.",
                            "fecha": "2025-09-09"
                            },
                            {
                            "id": "E2",
                            "titulo": "Carta documento actor",
                            "descripcion": "Intimación y puesta en mora (arts. 2, 11, 245 LCT).",
                            "fecha": "2025-09-15",
                            "plazo_limite": "2025-09-22"
                            },
                            {
                            "id": "E3",
                            "titulo": "Presentación demanda",
                            "descripcion": "Ingreso de demanda con planilla de liquidación, ofrecimiento de prueba y documental.",
                            "fecha": "2025-10-03"
                            },
                            {
                            "id": "E4",
                            "titulo": "Control de plazos (HOY)",
                            "descripcion": "Verificar vencimiento de traslado y plazo para oponer excepciones.",
                            "fecha": "2025-10-05",
                            "plazo_limite": "2025-10-12"
                            },
                            {
                            "id": "E5",
                            "titulo": "Traslado de demanda",
                            "descripcion": "Cédula notificada a la demandada. Comienza a correr el plazo de contestación.",
                            "fecha": "2025-10-08",
                            "plazo_limite": "2025-10-29"
                            },
                            {
                            "id": "E6",
                            "titulo": "Contestación de demanda",
                            "descripcion": "Presentación de contestación con negativa y ofrecimiento de prueba.",
                            "fecha": "2025-10-20"
                            },
                            {
                            "id": "E7",
                            "titulo": "Audiencia de conciliación obligatoria",
                            "descripcion": "Audiencia ante el juzgado. Las partes deben comparecer con facultades para conciliar.",
                            "fecha": "2025-11-10",
                            "plazo_limite": "2025-11-05"
                            },
                            {
                            "id": "E8",
                            "titulo": "Apertura a prueba",
                            "descripcion": "Se abre la causa a prueba por 40 días.",
                            "fecha": "2025-11-20"
                            },
                            {
                            "id": "E9",
                            "titulo": "Pericia contable",
                            "descripcion": "Designación y aceptación del perito contable. Carga de puntos de pericia.",
                            "fecha": "2025-12-01",
                            "plazo_limite": "2025-12-08"
                            },
                            {
                            "id": "E10",
                            "titulo": "Producción testimonial",
                            "descripcion": "Declaración de Carlos Ruiz y otros testigos.",
                            "fecha": "2025-12-15"
                            },
                            {
                            "id": "E11",
                            "titulo": "Cierre de prueba",
                            "descripcion": "Vencimiento del período probatorio.",
                            "fecha": "2026-01-15"
                            },
                            {
                            "id": "E12",
                            "titulo": "Alegatos",
                            "descripcion": "Presentación de alegatos por escrito.",
                            "fecha": "2026-01-30",
                            "plazo_limite": "2026-02-05"
                            }
                        ],

                        "grafo": {
                            "data": {
                            "nodes": [
                                { "id": "P1", "label": "Juan Pérez", "type": "PERSONA", "role": "Actor" },
                                { "id": "P2", "label": "Acme S.A.", "type": "ORGANIZACION", "role": "Demandado" },
                                { "id": "P3", "label": "Lucía Fernández", "type": "PERSONA", "role": "Abogada Actor" },
                                { "id": "P4", "label": "María Gómez", "type": "PERSONA", "role": "Abogada Demandada" },
                                { "id": "P5", "label": "Carlos Ruiz", "type": "PERSONA", "role": "Testigo" },

                                { "id": "J1", "label": "Juzg. Nac. del Trabajo N° 45", "type": "TRIBUNAL" },
                                { "id": "C1", "label": "Despido sin causa", "type": "CONCEPTO" },
                                { "id": "C2", "label": "Indemnización art. 245 LCT", "type": "CONCEPTO" },
                                { "id": "C3", "label": "Multa art. 2 Ley 25.323", "type": "CONCEPTO" },

                                { "id": "E1", "label": "Despido (2025-09-09)", "type": "EVENTO" },
                                { "id": "E2", "label": "CD Intimación (2025-09-15)", "type": "EVENTO" },
                                { "id": "E3", "label": "Demanda (2025-10-03)", "type": "EVENTO" },
                                { "id": "E5", "label": "Traslado (2025-10-08)", "type": "EVENTO" },
                                { "id": "E6", "label": "Contesta Demanda (2025-10-20)", "type": "EVENTO" },
                                { "id": "E7", "label": "Audiencia (2025-11-10)", "type": "EVENTO" },
                                { "id": "E9", "label": "Pericia Contable (2025-12-01)", "type": "EVENTO" },

                                { "id": "D1", "label": "CD Actor 15/09", "type": "DOCUMENTO" },
                                { "id": "D2", "label": "Planilla de liquidación", "type": "DOCUMENTO" },
                                { "id": "D3", "label": "Recibos de sueldo 2024-2025", "type": "DOCUMENTO" },
                                { "id": "D4", "label": "Contestación de demanda", "type": "DOCUMENTO" }
                            ],
                            "edges": [
                                { "from": "P1", "to": "E1", "label": "protagoniza" },
                                { "from": "P2", "to": "E1", "label": "decide despido" },
                                { "from": "P1", "to": "E2", "label": "remite CD" },
                                { "from": "D1", "to": "E2", "label": "documenta" },

                                { "from": "P3", "to": "E3", "label": "patrocina demanda" },
                                { "from": "P1", "to": "E3", "label": "promueve" },
                                { "from": "D2", "to": "E3", "label": "adjunta" },
                                { "from": "D3", "to": "E3", "label": "adjunta" },

                                { "from": "J1", "to": "E5", "label": "notifica traslado" },
                                { "from": "P2", "to": "E6", "label": "contesta" },
                                { "from": "P4", "to": "E6", "label": "patrocina" },
                                { "from": "D4", "to": "E6", "label": "presenta" },

                                { "from": "J1", "to": "E7", "label": "convoca audiencia" },
                                { "from": "P1", "to": "E7", "label": "comparece" },
                                { "from": "P2", "to": "E7", "label": "comparece" },

                                { "from": "E1", "to": "C1", "label": "califica" },
                                { "from": "E3", "to": "C2", "label": "reclama" },
                                { "from": "E3", "to": "C3", "label": "reclama" },

                                { "from": "J1", "to": "E9", "label": "designa perito" },
                                { "from": "P5", "to": "E10", "label": "declara" },

                                { "from": "E2", "to": "E3", "label": "antecedente" },
                                { "from": "E3", "to": "E5", "label": "origina traslado" },
                                { "from": "E5", "to": "E6", "label": "da lugar a" },
                                { "from": "E6", "to": "E7", "label": "previa a audiencia" }
                            ]
                            }
                        },
                        "metadatos": {
                            "moneda": "ARS",
                            "monto_reclamado_aprox": 12500000,
                            "tags": ["laboral", "despido", "CABA", "pericia contable", "audiencia"]
                        }
                }
            )
        ],
        tags=["Causas"]
    )
    @action(detail=False, methods=["post"], url_path="full", permission_classes=[permissions.IsAuthenticated])
    def create_full(self, request):
        ser = CausaFullCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        causa = ser.save()
        status_code = status.HTTP_200_OK if request.data.get("idempotency_key") else status.HTTP_201_CREATED
        return Response(ser.to_representation(causa), status=status_code)




@extend_schema_view(
    list=extend_schema(summary="Listar eventos", description="Lista paginada con filtros, búsqueda y orden."),
    retrieve=extend_schema(summary="Ver un evento", description="Recupera un evento por ID."),
    create=extend_schema(summary="Crear evento", description="Crea un nuevo evento procesal."),
    update=extend_schema(summary="Actualizar evento (PUT)", description="Reemplaza completamente el evento."),
    partial_update=extend_schema(summary="Actualizar evento (PATCH)", description="Actualiza parcialmente el evento."),
    destroy=extend_schema(summary="Eliminar evento", description="Elimina un evento por ID."),
)
@extend_schema(tags=["Eventos"])
class EventoProcesalViewSet(viewsets.ModelViewSet):
    queryset = EventoProcesal.objects.all().order_by("fecha", "id")
    serializer_class = EventoProcesalSerializer
    permission_classes = ALLOW

    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventoFilter
    search_fields = ["titulo", "descripcion"]
    ordering_fields = ["fecha", "plazo_limite", "creado_en"]

    def get_queryset(self):
        return (EventoProcesal.objects
                .filter(causa__creado_por=self.request.user)
                .order_by("fecha", "id"))

    @extend_schema(
        summary="Próximos eventos (global)",
        description="Lista eventos próximos por fecha o por plazo_limite. Permite filtrar por causa.",
        parameters=[
            OpenApiParameter("dias", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Días hacia adelante (default 14)"),
            OpenApiParameter("solo_con_plazo", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="1/true para solo eventos con plazo definido"),
            OpenApiParameter("causa", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Filtrar por ID de causa"),
            OpenApiParameter("desde_hoy", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="1/true para empezar en hoy (si no, desde ayer)"),
        ],
        responses={200: ProximosResponseSerializer},
    )
    @action(detail=False, methods=["get"], url_path="proximos")
    def proximos(self, request):
        try:
            dias = int(request.query_params.get("dias", 14))
        except ValueError:
            dias = 14

        hoy = date.today()
        desde = hoy if request.query_params.get("desde_hoy") in {"1", "true", "True"} else (hoy - timedelta(days=1))
        hasta = hoy + timedelta(days=dias)

        qs = EventoProcesal.objects.all()
        if request.query_params.get("solo_con_plazo") in {"1", "true", "True"}:
            qs = qs.filter(plazo_limite__isnull=False)

        causa = request.query_params.get("causa")
        if causa:
            qs = qs.filter(causa_id=causa)

        qs = qs.filter(
            models.Q(fecha__range=(desde, hasta)) |
            models.Q(plazo_limite__range=(desde, hasta))
        ).order_by("plazo_limite", "fecha", "id")

        data = EventoProcesalSerializer(qs, many=True).data
        return Response({"desde": desde, "hasta": hasta, "eventos": data})

# Resto de viewsets (con filtros básicos para comodidad)

class ParteFilter(dj_filters.FilterSet):
    # permite /api/partes/?causa=7
    causa = dj_filters.NumberFilter(field_name="en_causas__causa_id", lookup_expr="exact")

    class Meta:
        model = Parte
        fields = ["causa", "tipo_persona", "documento", "cuit_cuil", "email"]



@extend_schema_view(
    list=extend_schema(summary="Listar partes"),
    retrieve=extend_schema(summary="Ver parte"),
    create=extend_schema(summary="Crear parte"),
    update=extend_schema(summary="Actualizar parte (PUT)"),
    partial_update=extend_schema(summary="Actualizar parte (PATCH)"),
    destroy=extend_schema(summary="Eliminar parte"),
)
@extend_schema(tags=["Partes"])
class ParteViewSet(viewsets.ModelViewSet):
    queryset = Parte.objects.all()
    serializer_class = ParteSerializer
    permission_classes = RESTRICTED_ALLOW
    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ParteFilter
    search_fields = ["nombre_razon_social", "documento", "cuit_cuil", "email"]
    ordering_fields = ["nombre_razon_social", "id"]




@extend_schema_view(
    list=extend_schema(summary="Listar rol_partes"),
    retrieve=extend_schema(summary="Ver rol_parte"),
    create=extend_schema(summary="Crear rol_parte"),
    update=extend_schema(summary="Actualizar rol_parte (PUT)"),
    partial_update=extend_schema(summary="Actualizar rol_parte (PATCH)"),
    destroy=extend_schema(summary="Eliminar rol_parte"),
)
@extend_schema(tags=["RolPartes"])
class RolParteViewSet(viewsets.ModelViewSet):
    queryset = RolParte.objects.all()
    serializer_class = RolParteSerializer
    permission_classes = RESTRICTED_ALLOW


@extend_schema_view(
    list=extend_schema(summary="Listar profesionales"),
    retrieve=extend_schema(summary="Ver profesional"),
    create=extend_schema(summary="Crear profesional"),
    update=extend_schema(summary="Actualizar profesional (PUT)"),
    partial_update=extend_schema(summary="Actualizar profesional (PATCH)"),
    destroy=extend_schema(summary="Eliminar profesional"),
)
@extend_schema(tags=["Profesionales"])
class ProfesionalViewSet(viewsets.ModelViewSet):
    queryset = Profesional.objects.all()
    serializer_class = ProfesionalSerializer
    permission_classes = RESTRICTED_ALLOW
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["apellido", "nombre", "matricula", "email"]
    ordering_fields = ["apellido", "nombre", "id"]
    def get_queryset(self):
        return CausaProfesional.objects.filter(causa__creado_por=self.request.user)





@extend_schema_view(
    list=extend_schema(summary="Listar causa_parte"),
    retrieve=extend_schema(summary="Ver causa_parte"),
    create=extend_schema(summary="Crear causa_parte"),
    update=extend_schema(summary="Actualizar causa_parte (PUT)"),
    partial_update=extend_schema(summary="Actualizar causa_parte (PATCH)"),
    destroy=extend_schema(summary="Eliminar causa_parte"),
)
@extend_schema(tags=["Causa_Parte"])
class CausaParteViewSet(viewsets.ModelViewSet):
    queryset = CausaParte.objects.all()
    serializer_class = CausaParteSerializer
    permission_classes = RESTRICTED_ALLOW
    filter_backends = [dj_filters.DjangoFilterBackend]
    filterset_fields = ["causa", "parte", "rol_parte"]
    def get_queryset(self):
        return CausaParte.objects.filter(causa__creado_por=self.request.user)


@extend_schema_view(
    list=extend_schema(summary="Listar causa_profesional"),
    retrieve=extend_schema(summary="Ver causa_profesional"),
    create=extend_schema(summary="Crear causa_profesional"),
    update=extend_schema(summary="Actualizar causa_profesional (PUT)"),
    partial_update=extend_schema(summary="Actualizar causa_profesional (PATCH)"),
    destroy=extend_schema(summary="Eliminar causa_profesional"),
)
@extend_schema(tags=["Causa_Profesional"])
class CausaProfesionalViewSet(viewsets.ModelViewSet):
    queryset = CausaProfesional.objects.all()
    serializer_class = CausaProfesionalSerializer
    permission_classes = RESTRICTED_ALLOW
    filter_backends = [dj_filters.DjangoFilterBackend]
    filterset_fields = ["causa", "profesional", "rol_profesional"]



# ---------- Upload a S3 (usando django-storages) ----------
@extend_schema_view(
    # Aplicamos la documentación a cada acción generada por el ViewSet
    list=extend_schema(summary="Listar documentos del usuario", tags=["Documentos"]),
    create=extend_schema(summary="Subir un nuevo documento", tags=["Documentos"]),
    retrieve=extend_schema(summary="Obtener un documento por ID", tags=["Documentos"]),
    destroy=extend_schema(summary="Borrar un documento por ID", tags=["Documentos"]),
)
class DocumentoViewSet(viewsets.ModelViewSet):
    """
    ViewSet que agrupa todas las operaciones para los Documentos.
    """
    serializer_class = DocumentoSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]
    
    # Mantenemos el filtro para 'causa'
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['causa']

    def get_queryset(self):
        """
        Asegura que todas las operaciones solo afecten a los documentos 
        del usuario autenticado.
        """
        if not self.request.user or self.request.user.is_anonymous:
            return Documento.objects.none()
        return Documento.objects.filter(usuario=self.request.user).order_by('-creado_en')

    def perform_create(self, serializer):
        """
        Al crear, extrae el título del nombre del archivo y asigna el usuario.
        """
        archivo = self.request.data.get("archivo")
        titulo_sin_extension, _ = os.path.splitext(archivo.name)
        serializer.save(usuario=self.request.user, titulo=titulo_sin_extension)

    @extend_schema(
        summary="Borrado masivo de documentos",
        request={"application/json": {"example": {"ids": [1, 2, 3]}}},
        responses={204: None},
        tags=["Documentos"]
    )
    @action(detail=False, methods=['delete'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """
        Acción personalizada para borrar múltiples documentos a la vez.
        """
        ids_a_borrar = request.data.get('ids', [])
        
        if not ids_a_borrar:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # Usamos el queryset base (que ya está filtrado por usuario)
        documentos = self.get_queryset().filter(id__in=ids_a_borrar)
        
        for doc in documentos:
            doc.delete() # Borramos uno a uno para activar la señal de S3
            
        return Response(status=status.HTTP_204_NO_CONTENT)
    



# Crear Causa desde Documento (usando AWS Textract + OpenAI) y SUMANDO ML
import pickle
from pathlib import Path
from datetime import date, timedelta
from tasks.models import Task
# ========== CARGA DEL MODELO ML ==========
ML_MODELS_PATH = Path(__file__).parent / 'ml_models'
VECTORIZER = None
CLASIFICADOR = None

def cargar_modelos_ml():
    """Carga los modelos ML una sola vez"""
    global VECTORIZER, CLASIFICADOR
    
    if VECTORIZER is None or CLASIFICADOR is None:
        try:
            with open(ML_MODELS_PATH / 'vectorizer.pkl', 'rb') as f:
                VECTORIZER = pickle.load(f)
            with open(ML_MODELS_PATH / 'clasificador.pkl', 'rb') as f:
                CLASIFICADOR = pickle.load(f)
            print("✅ Modelos ML cargados correctamente")
        except FileNotFoundError:
            print("⚠️ Modelos ML no encontrados en ml_models/")
            return None, None
    
    return VECTORIZER, CLASIFICADOR


# ========== MAPEO DE ETAPAS ML A ESTADOS DE CAUSA ==========
MAPEO_ESTADOS = {
    'seclo': 'abierta',
    'demanda_inicial': 'en_tramite',
    'prueba': 'en_tramite',
    'sentencia': 'con_sentencia',
    'desconocido': 'abierta'
}


# ========== BASE DE CONOCIMIENTO DE EVENTOS POR ETAPA ==========
EVENTOS_POR_ETAPA = {
    'seclo': {
        'eventos_pasados': [
            {
                'titulo': 'Presentación en SECLO',
                'descripcion': 'Reclamo presentado ante el Servicio de Conciliación Laboral Obligatoria. Creado con Machine Learning.',
                'dias_antes': 20
            },
            {
                'titulo': 'Notificación al empleador',
                'descripcion': 'El SECLO notifica al empleador mediante cédula. Creado con Machine Learning.',
                'dias_antes': 13
            }
        ],
        'eventos_actuales': [
            {
                'titulo': 'Audiencia de conciliación SECLO',
                'descripcion': 'Audiencia obligatoria de conciliación prelegal. CRÍTICO: Comparecencia obligatoria. Creado con Machine Learning.',
                'plazo_dias': 7,
                'es_plazo_limite': True
            },
            {
                'titulo': 'Obtener certificado habilitante',
                'descripcion': 'Si fracasa la conciliación, obtener certificado para habilitar vía judicial (90 días para demandar). Creado con Machine Learning.',
                'plazo_dias': 10,
                'es_plazo_limite': True
            }
        ],
        'tasks': [
            {
                'content': 'Preparar documentación laboral completa (recibos de sueldo, telegrama de despido)',
                'priority': 'high',
                'deadline_dias': 5
            },
            {
                'content': 'Si hay acuerdo en SECLO, considerar homologación ante Ministerio de Trabajo',
                'priority': 'medium',
                'deadline_dias': 30
            }
        ]
    },
    'demanda_inicial': {
        'eventos_pasados': [
            {
                'titulo': 'Certificado habilitante SECLO obtenido',
                'descripcion': 'Fracaso de conciliación prelegal. Vía judicial habilitada. Creado con Machine Learning.',
                'dias_antes': 45
            },
            {
                'titulo': 'Presentación de demanda judicial',
                'descripcion': 'Demanda presentada ante Juzgado Laboral. Creado con Machine Learning.',
                'dias_antes': 15
            },
            {
                'titulo': 'Sorteo y asignación de juzgado',
                'descripcion': 'Juzgado asignado aleatoriamente y expediente iniciado. Creado con Machine Learning.',
                'dias_antes': 10
            }
        ],
        'eventos_actuales': [
            {
                'titulo': 'Traslado de demanda (10 días hábiles)',
                'descripcion': 'PLAZO PERENTORIO: El demandado tiene 10 días hábiles para contestar desde la notificación. Creado con Machine Learning.',
                'plazo_dias': 10,
                'es_plazo_limite': True
            },
            {
                'titulo': 'Audiencia Art. 58 - Conciliación judicial',
                'descripcion': 'Audiencia de conciliación obligatoria ante el juez. La incomparecencia puede generar consecuencias graves. Creado con Machine Learning.',
                'plazo_dias': 20,
                'es_plazo_limite': False
            }
        ],
        'tasks': [
            {
                'content': 'CRÍTICO: Verificar que la demanda incluya certificado habilitante SECLO',
                'priority': 'high',
                'deadline_dias': 2
            },
            {
                'content': 'Preparar documentación para audiencia Art. 58 (recibos, contratos, comunicaciones)',
                'priority': 'high',
                'deadline_dias': 15
            },
            {
                'content': 'Revisar si el demandado contestó la demanda dentro del plazo',
                'priority': 'medium',
                'deadline_dias': 12
            }
        ]
    },
    'prueba': {
        'eventos_pasados': [
            {
                'titulo': 'Etapa SECLO completada',
                'descripcion': 'Conciliación prelegal finalizada sin acuerdo. Creado con Machine Learning.',
                'dias_antes': 90
            },
            {
                'titulo': 'Demanda y contestación presentadas',
                'descripcion': 'Ambas partes han presentado sus escritos iniciales. Creado con Machine Learning.',
                'dias_antes': 60
            },
            {
                'titulo': 'Audiencia Art. 58 realizada',
                'descripcion': 'Intento de conciliación judicial fracasado. Se procede a prueba. Creado con Machine Learning.',
                'dias_antes': 30
            },
            {
                'titulo': 'Apertura a prueba (40 días hábiles)',
                'descripcion': 'Causa abierta a prueba por 40 días hábiles judiciales. Creado con Machine Learning.',
                'dias_antes': 10
            }
        ],
        'eventos_actuales': [
            {
                'titulo': 'Producción de prueba documental',
                'descripcion': 'Presentar y agregar documentación probatoria. Creado con Machine Learning.',
                'plazo_dias': 15,
                'es_plazo_limite': False
            },
            {
                'titulo': 'Designación de peritos',
                'descripcion': 'Proponer peritos contadores y observar los de la contraria. Creado con Machine Learning.',
                'plazo_dias': 20,
                'es_plazo_limite': False
            },
            {
                'titulo': 'Audiencias testimoniales',
                'descripcion': 'Citar testigos y coordinar fechas de audiencia. Creado con Machine Learning.',
                'plazo_dias': 25,
                'es_plazo_limite': False
            },
            {
                'titulo': 'Clausura de prueba',
                'descripcion': 'CRÍTICO: Vencimiento del plazo de 40 días hábiles para producir prueba. Creado con Machine Learning.',
                'plazo_dias': 40,
                'es_plazo_limite': True
            }
        ],
        'tasks': [
            {
                'content': 'Gestionar oficios a AFIP, ANSES y ART (si corresponde)',
                'priority': 'high',
                'deadline_dias': 10
            },
            {
                'content': 'Coordinar con peritos contadores designados',
                'priority': 'high',
                'deadline_dias': 15
            },
            {
                'content': 'Preparar pliego de preguntas para testigos',
                'priority': 'medium',
                'deadline_dias': 20
            },
            {
                'content': 'Reiterar oficios no respondidos',
                'priority': 'medium',
                'deadline_dias': 25
            }
        ]
    },
    'sentencia': {
        'eventos_pasados': [
            {
                'titulo': 'Proceso completo realizado',
                'descripcion': 'Todas las etapas procesales completadas: SECLO, demanda, prueba y alegatos. Creado con Machine Learning.',
                'dias_antes': 180
            },
            {
                'titulo': 'Clausura de prueba',
                'descripcion': 'Finalizado el período probatorio de 40 días hábiles. Creado con Machine Learning.',
                'dias_antes': 30
            },
            {
                'titulo': 'Alegatos presentados',
                'descripcion': 'Ambas partes presentaron alegatos sobre el mérito de la prueba. Creado con Machine Learning.',
                'dias_antes': 20
            },
            {
                'titulo': 'Llamamiento de autos para sentencia',
                'descripcion': 'Expediente a despacho del juez para dictar fallo. Creado con Machine Learning.',
                'dias_antes': 10
            }
        ],
        'eventos_actuales': [
            {
                'titulo': 'Sentencia de primera instancia',
                'descripcion': 'El juez ha dictado sentencia resolviendo la causa. Analizar resultado. Creado con Machine Learning.',
                'plazo_dias': 0,
                'es_plazo_limite': False
            },
            {
                'titulo': 'Plazo para apelar (5 días hábiles)',
                'descripcion': 'CRÍTICO: Plazo perentorio para interponer recurso de apelación si la sentencia es desfavorable. Creado con Machine Learning.',
                'plazo_dias': 5,
                'es_plazo_limite': True
            }
        ],
        'tasks': [
            {
                'content': 'Analizar sentencia: determinar si es favorable, parcial o desfavorable',
                'priority': 'high',
                'deadline_dias': 1
            },
            {
                'content': 'Si es favorable: preparar liquidación de condena (capital + intereses + costas)',
                'priority': 'high',
                'deadline_dias': 7
            },
            {
                'content': 'Si es desfavorable: decidir si apelar y preparar expresión de agravios',
                'priority': 'high',
                'deadline_dias': 3
            },
            {
                'content': 'Revisar imposición de costas procesales',
                'priority': 'medium',
                'deadline_dias': 5
            }
        ]
    },
    'desconocido': {
        'eventos_pasados': [],
        'eventos_actuales': [
            {
                'titulo': 'Clasificación manual requerida',
                'descripcion': 'No se pudo identificar automáticamente la etapa procesal. Revisar documento y clasificar manualmente. Creado con Machine Learning.',
                'plazo_dias': 1,
                'es_plazo_limite': True
            }
        ],
        'tasks': [
            {
                'content': 'Revisar documento PDF subido y determinar etapa procesal manualmente',
                'priority': 'high',
                'deadline_dias': 1
            },
            {
                'content': 'Verificar que sea un documento procesal laboral de CABA/Buenos Aires',
                'priority': 'medium',
                'deadline_dias': 1
            }
        ]
    }
}

# ========== FUNCIÓN DE CLASIFICACIÓN ML ==========
def clasificar_documento_ml(texto_documento):
    """
    Clasifica la etapa procesal usando el modelo ML entrenado
    
    Returns:
        dict con etapa, confianza, eventos y tasks
    """
    vectorizer, clf = cargar_modelos_ml()
    
    if vectorizer is None or clf is None:
        return {
            'etapa': 'desconocido',
            'confianza': 0.0,
            'error': 'Modelos ML no disponibles'
        }
    
    try:
        # Clasificar
        texto_vec = vectorizer.transform([texto_documento.lower()])
        etapa_predicha = clf.predict(texto_vec)[0]
        probabilidades = clf.predict_proba(texto_vec)[0]
        confianza = max(probabilidades)
        
        # Obtener configuración de la etapa
        config_etapa = EVENTOS_POR_ETAPA.get(etapa_predicha, EVENTOS_POR_ETAPA['desconocido'])
        
        return {
            'etapa': etapa_predicha,
            'confianza': float(confianza),
            'estado_causa': MAPEO_ESTADOS[etapa_predicha],
            'eventos_pasados': config_etapa['eventos_pasados'],
            'eventos_actuales': config_etapa['eventos_actuales'],
            'tasks': config_etapa.get('tasks', [])
        }
    
    except Exception as e:
        print(f"Error en clasificación ML: {e}")
        return {
            'etapa': 'desconocido',
            'confianza': 0.0,
            'error': str(e)
        }
    


















# ========== VISTA PRINCIPAL ==========
@extend_schema(
    summary="Crear Causa desde Documento (con ML opcional)",
    description="Sube un documento, extrae datos con IA y opcionalmente usa ML para clasificar etapa procesal.",
    request=DocumentoCreaCausaSerializer,
    responses={201: CausaSerializer}
)
class CausaDesdeDocumentoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [parsers.MultiPartParser]
    
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        archivo = request.data.get('archivo')
        use_ml = request.data.get('use_ml', 'false')
        
        if not archivo:
            return Response(
                {"error": "No se proporcionó ningún archivo."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        use_ml_bool = use_ml.lower() == 'true'

        try:
            # ========== 1. VALIDAR ARCHIVO ==========
            archivo_nombre = archivo.name
            archivo_content_type = archivo.content_type
            archivo_size = archivo.size
            archivo_bytes = archivo.read()
            
            # Constantes de tamaño
            MAX_SIZE_SYNC_MB = 5      # Método síncrono (rápido)
            MAX_SIZE_ASYNC_MB = 500   # Método asíncrono (lento pero soporta archivos grandes)
            
            archivo_size_mb = archivo_size / 1024 / 1024
            
            print(f"\n{'='*60}")
            print(f"📄 PROCESANDO DOCUMENTO")
            print(f"{'='*60}")
            print(f"Nombre: {archivo_nombre}")
            print(f"Tamaño: {archivo_size_mb:.2f} MB")
            print(f"Tipo: {archivo_content_type}")
            print(f"use_ml: {use_ml_bool}")
            
            # Verificar límite máximo
            if archivo_size_mb > MAX_SIZE_ASYNC_MB:
                return Response(
                    {
                        "error": f"Archivo demasiado grande ({archivo_size_mb:.2f} MB). Máximo permitido: {MAX_SIZE_ASYNC_MB} MB",
                        "sugerencia": "Por favor comprima el PDF o divídalo en archivos más pequeños"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verificar que sea un PDF válido
            if not archivo_bytes.startswith(b'%PDF'):
                return Response(
                    {"error": "El archivo no es un PDF válido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # ========== 2. SUBIR A S3 ==========
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                aws_session_token=settings.AWS_SESSION_TOKEN,
                region_name=settings.AWS_REGION_NAME
            )
            
            file_name = f"temp/{uuid.uuid4()}/{archivo_nombre}"
            bucket_name = settings.AWS_STORAGE_BUCKET_NAME
            
            print(f"\n📤 Subiendo a S3: {file_name}")
            
            s3_client.put_object(
                Bucket=bucket_name,
                Key=file_name,
                Body=archivo_bytes,
                ContentType='application/pdf'  # Forzar PDF
            )
            
            print(f"✅ Archivo subido a S3")
            
            # ========== 3. TEXTRACT (SÍNCRONO O ASÍNCRONO) ==========
            textract_client = boto3.client(
                'textract',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                aws_session_token=settings.AWS_SESSION_TOKEN,
                region_name=settings.AWS_REGION_NAME
            )
            
            texto_documento = ""
            
            if archivo_size_mb > MAX_SIZE_SYNC_MB:
                # ========== MÉTODO ASÍNCRONO (archivos > 5MB) ==========
                print(f"\n🔄 Archivo grande, usando Textract ASÍNCRONO...")
                print(f"   Esto puede tardar 10-60 segundos...")
                
                # Iniciar job
                response = textract_client.start_document_text_detection(
                    DocumentLocation={
                        'S3Object': {
                            'Bucket': bucket_name,
                            'Name': file_name
                        }
                    }
                )
                
                job_id = response['JobId']
                print(f"   Job ID: {job_id}")
                
                # Polling: esperar a que termine
                import time
                max_attempts = 60  # 60 intentos x 2 segundos = 2 minutos máx
                attempt = 0
                
                while attempt < max_attempts:
                    time.sleep(2)
                    
                    result = textract_client.get_document_text_detection(JobId=job_id)
                    job_status = result['JobStatus']
                    
                    if attempt % 5 == 0:  # Mostrar cada 10 segundos
                        print(f"   [{attempt * 2}s] Estado: {job_status}")
                    
                    if job_status == 'SUCCEEDED':
                        print(f"✅ Textract completado en {attempt * 2} segundos")
                        
                        # Extraer todo el texto (puede haber múltiples páginas)
                        for item in result["Blocks"]:
                            if item["BlockType"] == "LINE":
                                texto_documento += item["Text"] + "\n"
                        
                        # Obtener páginas adicionales si las hay
                        next_token = result.get('NextToken')
                        while next_token:
                            result = textract_client.get_document_text_detection(
                                JobId=job_id,
                                NextToken=next_token
                            )
                            for item in result["Blocks"]:
                                if item["BlockType"] == "LINE":
                                    texto_documento += item["Text"] + "\n"
                            next_token = result.get('NextToken')
                        
                        break
                        
                    elif job_status == 'FAILED':
                        error_msg = result.get('StatusMessage', 'Error desconocido')
                        print(f"❌ Textract falló: {error_msg}")
                        return Response(
                            {"error": f"Textract no pudo procesar el documento: {error_msg}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                    
                    attempt += 1
                
                if attempt >= max_attempts:
                    return Response(
                        {"error": "Timeout: el procesamiento de Textract tardó demasiado (>2 minutos)"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            
            else:
                # ========== MÉTODO SÍNCRONO (archivos < 5MB) ==========
    # ========== MÉTODO SÍNCRONO (archivos < 5MB) ==========
                import logging
                logger = logging.getLogger(__name__)
                
                logger.info(f"⚡ Archivo pequeño ({archivo_size_mb:.2f} MB), usando método SÍNCRONO")
                logger.info(f"   S3 Bucket: {bucket_name}")
                logger.info(f"   S3 Key: {file_name}")
                
                # VALIDAR que el archivo se subió bien
                try:
                    obj_info = s3_client.head_object(Bucket=bucket_name, Key=file_name)
                    logger.info(f"✅ Archivo verificado en S3:")
                    logger.info(f"   - Content-Type: {obj_info.get('ContentType')}")
                    logger.info(f"   - Tamaño: {obj_info.get('ContentLength')} bytes")
                    
                    # Validar Content-Type
                    if obj_info.get('ContentType') not in ['application/pdf', 'binary/octet-stream']:
                        logger.error(f"❌ Content-Type inválido: {obj_info.get('ContentType')}")
                        return Response(
                            {"error": f"Content-Type inválido: {obj_info.get('ContentType')}. Debe ser application/pdf"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                
                except Exception as e:
                    logger.error(f"❌ Error verificando S3: {e}")
                    return Response(
                        {"error": f"El archivo no existe en S3: {e}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                
                # Intentar Textract
                try:
                    logger.info("🔍 Llamando a Textract...")
                    
                    response = textract_client.detect_document_text(
                        Document={
                            'S3Object': {
                                'Bucket': bucket_name,
                                'Name': file_name
                            }
                        }
                    )
                    
                    logger.info(f"✅ Textract OK: {len(response.get('Blocks', []))} bloques")
                    
                except Exception as textract_error:
                    logger.error(f"❌ Error Textract: {textract_error}")
                    logger.error(f"   Bucket: {bucket_name}")
                    logger.error(f"   Key: {file_name}")
                    
                    # Intentar descargar el archivo de S3 para verificar
                    try:
                        obj = s3_client.get_object(Bucket=bucket_name, Key=file_name)
                        downloaded_bytes = obj['Body'].read()
                        logger.error(f"   Archivo descargado: {len(downloaded_bytes)} bytes")
                        logger.error(f"   Primeros 10 bytes: {downloaded_bytes[:10]}")
                        logger.error(f"   Es PDF válido: {downloaded_bytes.startswith(b'%PDF')}")
                    except Exception as download_error:
                        logger.error(f"   No se pudo descargar: {download_error}")
                    
                    raise  # Re-lanzar el error original
                
                texto_documento = ""
                for item in response["Blocks"]:
                    if item["BlockType"] == "LINE":
                        texto_documento += item["Text"] + "\n"
                
                logger.info(f"✅ Texto extraído: {len(texto_documento)} caracteres")

            # ========== 4. CLASIFICACIÓN ML ==========
            resultado_ml = None
            if use_ml_bool:
                print("🤖 Clasificando documento con ML...")
                resultado_ml = clasificar_documento_ml(texto_documento)
                print(f"✓ Etapa detectada: {resultado_ml['etapa']} (confianza: {resultado_ml['confianza']:.2%})")

            # ========== 5. OPENAI ==========
            if use_ml_bool and resultado_ml:
                prompt_complemento = f"""
                
                INFORMACIÓN DE CONTEXTO (detectada por ML):
                - Etapa procesal: {resultado_ml['etapa']}
                - Confianza: {resultado_ml['confianza']:.2%}
                """
            else:
                prompt_complemento = ""

            prompt = f"""
            Eres un asistente legal experto en analizar documentos judiciales de Argentina.
            Extrae la siguiente información. Devuelve únicamente JSON válido.
            {prompt_complemento}

            TEXTO DEL DOCUMENTO:
            ---
            {texto_documento}
            ---

            FORMATO JSON REQUERIDO:
            {{
            "fuero": "string",
            "numero_expediente": "string",
            "caratula": "string",
            "jurisdiccion": "string",
            "fecha_inicio": "string en formato YYYY-MM-DD",
            "estado": "string",
            "partes": [
                {{"nombre": "string", "rol": "string", "tipo_persona": "string (F/J)", "documento": "string"}}
            ]
            }}
            """

            cliente_ia = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            respuesta_ia = cliente_ia.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}]
            )
            
            raw_content = respuesta_ia.choices[0].message.content
            json_start = raw_content.find('{')
            json_end = raw_content.rfind('}') + 1
            json_string = raw_content[json_start:json_end]
            datos_extraidos = json.loads(json_string)
            
            # Recrear archivo
            archivo = ContentFile(archivo_bytes, name=archivo_nombre)

        except Exception as e:
            print(f"\n❌ ERROR:")
            import traceback
            traceback.print_exc()
            
            return Response(
                {"error": f"Error al procesar el documento: {e}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # ========== 6. CREAR CAUSA Y DATOS ==========
        try:
            # Determinar estado
            if use_ml_bool and resultado_ml:
                estado_causa = resultado_ml['estado_causa']
            else:
                estado_causa = datos_extraidos.get('estado') or "abierta"
            
            causa = Causa.objects.create(
                creado_por=request.user,
                fuero=datos_extraidos.get('fuero') or '',
                numero_expediente=datos_extraidos.get('numero_expediente') or '',
                caratula=datos_extraidos.get('caratula') or '',
                jurisdiccion=datos_extraidos.get('jurisdiccion') or '',
                fecha_inicio=datos_extraidos.get('fecha_inicio') or None,
                estado=estado_causa
            )
            
            # Crear Documento
            titulo_sin_extension, _ = os.path.splitext(archivo_nombre)
            Documento.objects.create(
                causa=causa,
                usuario=request.user,
                archivo=archivo,
                titulo=titulo_sin_extension,
                mime=archivo_content_type,
                size=archivo_size
            )
            
            # ========== 7. CREAR EVENTOS SI use_ml=true ==========
            if use_ml_bool and resultado_ml:
                fecha_hoy = timezone.now().date()
                
                # Eventos pasados
                for evento_config in resultado_ml['eventos_pasados']:
                    fecha_evento = fecha_hoy - timedelta(days=evento_config.get('dias_antes', 0))
                    EventoProcesal.objects.create(
                        causa=causa,
                        titulo=evento_config['titulo'],
                        descripcion=evento_config['descripcion'],
                        fecha=fecha_evento
                    )
                
                # Eventos actuales/futuros
                for evento_config in resultado_ml['eventos_actuales']:
                    plazo_dias = evento_config.get('plazo_dias', 7)
                    fecha_evento = fecha_hoy + timedelta(days=plazo_dias)
                    
                    EventoProcesal.objects.create(
                        causa=causa,
                        titulo=evento_config['titulo'],
                        descripcion=evento_config['descripcion'],
                        fecha=fecha_evento,
                        plazo_limite=fecha_evento if evento_config.get('es_plazo_limite') else None
                    )
            
            # ========== 8. CREAR TASKS SI use_ml=true ==========
            if use_ml_bool and resultado_ml:
                fecha_hoy = timezone.now().date()
                
                for task_config in resultado_ml.get('tasks', []):
                    deadline_dias = task_config.get('deadline_dias', 7)
                    deadline = fecha_hoy + timedelta(days=deadline_dias)
                    
                    Task.objects.create(
                        causa=causa,
                        content=task_config['content'],
                        priority=task_config.get('priority', 'medium'),
                        deadline_date=deadline,
                        status='pending'
                    )
            
            # ========== 9. CREAR PARTES ==========
            partes_data = datos_extraidos.get('partes', [])
            for parte_data in partes_data:
                if parte_data.get('nombre'):
                    # Crear o buscar Parte
                    parte, created = Parte.objects.get_or_create(
                        nombre_razon_social=parte_data['nombre'],
                        defaults={
                            'tipo_persona': parte_data.get('tipo_persona', 'F'),
                            'documento': parte_data.get('documento', ''),
                            'cuit_cuil': parte_data.get('cuit_cuil', '')
                        }
                    )
                    
                    # Crear relación CausaParte
                    CausaParte.objects.create(
                        causa=causa,
                        parte=parte
                    )
            
            # 10. Preparar respuesta
            serializer_respuesta = CausaSerializer(causa)
            response_data = serializer_respuesta.data
            
            # Agregar info de ML
            if use_ml_bool and resultado_ml:
                response_data['ml_info'] = {
                    'etapa_detectada': resultado_ml['etapa'],
                    'confianza': resultado_ml['confianza'],
                    'eventos_generados': len(resultado_ml['eventos_pasados']) + len(resultado_ml['eventos_actuales']),
                    'tasks_generadas': len(resultado_ml.get('tasks', []))
                }
            
            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            print(f"\n❌ ERROR AL GUARDAR:")
            import traceback
            traceback.print_exc()
            
            return Response(
                {"error": f"Error al guardar los datos: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )





