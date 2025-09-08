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


# Add this method inside the CausaViewSet class, after the other @action methods

