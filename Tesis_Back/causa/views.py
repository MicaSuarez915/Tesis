from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django_filters import rest_framework as dj_filters
from django.utils import timezone
from datetime import timedelta, date

from .models import *
from .serializers import *
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes, OpenApiExample
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
import unicodedata
import os
import re
import uuid
import boto3
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings

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

    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CausaFilter
    search_fields = ["numero_expediente", "caratula", "fuero", "jurisdiccion", "estado"]
    ordering_fields = ["fecha_inicio", "creado_en", "actualizado_en", "numero_expediente"]

    def get_queryset(self):
        # Sólo causas creadas por el usuario autenticado
        return Causa.objects.filter(creado_por=self.request.user).order_by("-id")

    def perform_create(self, serializer):
        # Seteá el dueño automáticamente
        serializer.save(creado_por=self.request.user)

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
    list=extend_schema(summary="Listar documentos"),
    retrieve=extend_schema(summary="Ver documento"),
    create=extend_schema(summary="Crear documento"),
    update=extend_schema(summary="Actualizar documento (PUT)"),
    partial_update=extend_schema(summary="Actualizar documento (PATCH)"),
    destroy=extend_schema(summary="Eliminar documento"),
)
@extend_schema(tags=["Documentos"])
class DocumentoViewSet(viewsets.ModelViewSet):
    queryset = Documento.objects.all()
    serializer_class = DocumentoSerializer
    permission_classes = RESTRICTED_ALLOW
    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["causa"]
    search_fields = ["titulo"]
    ordering_fields = ["fecha", "creado_en", "id"]
    def get_queryset(self):
        return Documento.objects.filter(causa__creado_por=self.request.user)


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


def slugify_filename(name: str) -> str:
    # slug “humano” para el nombre manteniendo extensión
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    base, ext = os.path.splitext(name)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:80] + ext  # acotar

def s3_client_and_bucket():
    """
    Retorna (client, bucket_name, storage) usando la configuración de django-storages.
    Si no hay DEFAULT_FILE_STORAGE configurado para S3, crea un cliente boto3 manual.
    """
    storage = default_storage

    # Caso 1: django-storages configurado con S3Boto3Storage
    if hasattr(storage, "connection") and hasattr(storage, "bucket"):
        s3_resource = storage.connection  # boto3.resource('s3')
        bucket = storage.bucket           # boto3.Bucket
        client = s3_resource.meta.client  # boto3.Client
        return client, bucket.name, storage

    # Caso 2: fallback manual (por si default_storage no es S3)
    client = boto3.client(
        "s3",
        region_name=getattr(settings, "AWS_S3_REGION_NAME", None)
        or getattr(settings, "AWS_REGION_NAME", "us-east-1"),
        aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", None),
        aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", None),
    )
    bucket_name = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None) \
        or getattr(settings, "AWS_DOCUMENTS_BUCKET_NAME", None)
    return client, bucket_name, storage

def ensure_prefix_exists(prefix: str, storage):
    if not prefix.endswith("/"):
        prefix += "/"
    marker = f"{prefix}.keep"        # o "_$folder$" o ".placeholder"
    if not storage.exists(marker):
        storage.save(marker, ContentFile(b""))

class S3TestUploadView(APIView):
    """
    POST /api/storage/test-upload/
    form-data: file=<archivo> [causa_id=<int>]
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        ser = S3TestUploadSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Intentar obtener el id directamente del token (por seguridad)
        auth = JWTAuthentication()
        raw_token = auth.get_raw_token(request.headers.get("Authorization", "").split("Bearer ")[-1])
        validated_token = auth.get_validated_token(raw_token)
        user_id = validated_token.get("user_id")

        # Si por alguna razón no viene, usar request.user.id
        if not user_id and hasattr(request.user, "id"):
            user_id = request.user.id   
        causa_id = ser.validated_data.get("causa_id")
        uploaded_file = ser.validated_data["file"]

        client, bucket_name, storage = s3_client_and_bucket()

        
        base_prefix = f"usuarios/{user_id}/"
        if causa_id:
            target_prefix = f"{base_prefix}causas/{causa_id}/"
        else:
            target_prefix = f"{base_prefix}varios/"

        # Asegurar “carpetas”
        ensure_prefix_exists(base_prefix, storage)
        if causa_id:
            ensure_prefix_exists(f"{base_prefix}causas", storage)
        ensure_prefix_exists(target_prefix, storage)

        # Armar nombre final
        safe_name = slugify_filename(uploaded_file.name)
        unique = uuid.uuid4().hex[:12]
        final_key = f"{target_prefix}{unique}__{safe_name}"

        # Setear content_type si vino del navegador
        content_type = getattr(uploaded_file, "content_type", None) or "application/octet-stream"
        # django-storages tomará content_type del file si está set
        uploaded_file.content_type = content_type

        # Guardar en S3 (usa DEFAULT_FILE_STORAGE)
        saved_key = storage.save(final_key, uploaded_file)

        # (Opcional) consultar metadatos (ETag, tamaño)
        return Response(
                {
                    "ok": True,
                    "bucket": bucket_name,
                    "key": saved_key,
                    "content_type": content_type,
                    "size_bytes": getattr(uploaded_file, "size", None),  # local
                    "etag": "",  # opcional: calcular hash local si querés
                    "uploaded_at": timezone.now().isoformat(),
                    "owner_user_id": user_id,
                    "owner_causa_id": causa_id,
                },
                status=status.HTTP_201_CREATED,
            )