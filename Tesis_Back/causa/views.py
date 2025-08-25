from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters import rest_framework as dj_filters
from django.utils import timezone
from datetime import timedelta, date
from .models import *
from .serializers import *

# Para desarrollo, permitimos acceso sin token:
ALLOW = [permissions.AllowAny]

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

# ---------- ViewSets con filtrado / búsqueda / orden ----------
class CausaViewSet(viewsets.ModelViewSet):
    queryset = Causa.objects.all().order_by("-id")
    serializer_class = CausaSerializer
    permission_classes = ALLOW

    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CausaFilter
    search_fields = ["numero_expediente", "caratula", "fuero", "jurisdiccion", "estado"]
    ordering_fields = ["fecha_inicio", "creado_en", "actualizado_en", "numero_expediente"]

    # /api/causas/{pk}/timeline/?desde=2025-08-01&hasta=2025-08-31&con_documentos=1
    @action(detail=True, methods=["get"], url_path="timeline")
    def timeline(self, request, pk=None):
        """
        Devuelve la línea de tiempo (eventos) de la causa, ordenados por fecha,
        con filtros opcionales de rango y anidado de documentos si se solicita.
        """
        causa = self.get_object()

        # filtros opcionales
        desde = request.query_params.get("desde")
        hasta = request.query_params.get("hasta")

        qs = causa.eventos.all().order_by("fecha", "id")
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)

        # serialización base de eventos
        data = EventoProcesalSerializer(qs, many=True).data

        # incluir documentos adjuntos de la causa si se pide &con_documentos=1
        if request.query_params.get("con_documentos") in {"1", "true", "True"}:
            documentos = DocumentoSerializer(causa.documentos.order_by("-fecha", "-id"), many=True).data
            return Response({"causa": causa.id, "eventos": data, "documentos": documentos})

        return Response({"causa": causa.id, "eventos": data})


class EventoProcesalViewSet(viewsets.ModelViewSet):
    queryset = EventoProcesal.objects.all().order_by("fecha", "id")
    serializer_class = EventoProcesalSerializer
    permission_classes = ALLOW

    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventoFilter
    search_fields = ["titulo", "descripcion"]
    ordering_fields = ["fecha", "plazo_limite", "creado_en"]

    # /api/eventos/proximos/?dias=14&solo_con_plazo=1&causa=1&desde_hoy=1
    @action(detail=False, methods=["get"], url_path="proximos")
    def proximos(self, request):
        """
        Lista eventos próximos (por fecha o por plazo_limite).
        - ?dias=14 (default 14)
        - ?solo_con_plazo=1 (opcional)
        - ?causa=ID (opcional)
        - ?desde_hoy=1 (si no, toma desde ayer para incluir rezagados)
        """
        try:
            dias = int(request.query_params.get("dias", 14))
        except ValueError:
            dias = 14

        hoy = date.today()
        desde = hoy if request.query_params.get("desde_hoy") in {"1", "true", "True"} else (hoy - timedelta(days=1))
        hasta = hoy + timedelta(days=dias)

        qs = EventoProcesal.objects.all()

        # solo eventos con plazo definido si se pide
        if request.query_params.get("solo_con_plazo") in {"1", "true", "True"}:
            qs = qs.filter(plazo_limite__isnull=False)

        # filtrar por causa si se indica
        causa = request.query_params.get("causa")
        if causa:
            qs = qs.filter(causa_id=causa)

        # próximos por fecha del evento O por plazo
        qs = qs.filter(
            models.Q(fecha__range=(desde, hasta)) |
            models.Q(plazo_limite__range=(desde, hasta))
        ).order_by("plazo_limite", "fecha", "id")

        data = EventoProcesalSerializer(qs, many=True).data
        return Response({"desde": desde, "hasta": hasta, "eventos": data})


# Resto de viewsets (con filtros básicos para comodidad)
class ParteViewSet(viewsets.ModelViewSet):
    queryset = Parte.objects.all()
    serializer_class = ParteSerializer
    permission_classes = ALLOW
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre_razon_social", "documento", "cuit_cuil", "email"]
    ordering_fields = ["nombre_razon_social", "id"]

class RolParteViewSet(viewsets.ModelViewSet):
    queryset = RolParte.objects.all()
    serializer_class = RolParteSerializer
    permission_classes = ALLOW

class ProfesionalViewSet(viewsets.ModelViewSet):
    queryset = Profesional.objects.all()
    serializer_class = ProfesionalSerializer
    permission_classes = ALLOW
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["apellido", "nombre", "matricula", "email"]
    ordering_fields = ["apellido", "nombre", "id"]

class DocumentoViewSet(viewsets.ModelViewSet):
    queryset = Documento.objects.all()
    serializer_class = DocumentoSerializer
    permission_classes = ALLOW
    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["causa"]
    search_fields = ["titulo"]
    ordering_fields = ["fecha", "creado_en", "id"]

class CausaParteViewSet(viewsets.ModelViewSet):
    queryset = CausaParte.objects.all()
    serializer_class = CausaParteSerializer
    permission_classes = ALLOW
    filter_backends = [dj_filters.DjangoFilterBackend]
    filterset_fields = ["causa", "parte", "rol_parte"]

class CausaProfesionalViewSet(viewsets.ModelViewSet):
    queryset = CausaProfesional.objects.all()
    serializer_class = CausaProfesionalSerializer
    permission_classes = ALLOW
    filter_backends = [dj_filters.DjangoFilterBackend]
    filterset_fields = ["causa", "profesional", "rol_profesional"]