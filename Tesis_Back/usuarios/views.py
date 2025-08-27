from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions, filters
from django.http import HttpResponse
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ViewSet
from .models import Usuario, Rol, EstudioJuridico, EstudioUsuario
from .serializers import (
    UsuarioSerializer, RolSerializer, EstudioJuridicoSerializer, EstudioUsuarioSerializer, HealthCheckSerializer
)
from drf_spectacular.utils import (
    extend_schema, extend_schema_view,
    OpenApiParameter, OpenApiTypes, OpenApiResponse, OpenApiExample
)
from django_filters import rest_framework as dj_filters



class IsSelfOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Usuario):
            return request.user.is_staff or obj.id == request.user.id
        return request.user.is_staff or request.user.is_superuser


# ---------- Usuarios ----------
@extend_schema(tags=["Usuarios"])
@extend_schema_view(
    list=extend_schema(
        summary="Listar usuarios",
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY,
                             description="Busca por email, nombre o apellido"),
            OpenApiParameter("ordering", OpenApiTypes.STR, OpenApiParameter.QUERY,
                             description="Campo de orden (id, email, first_name, last_name, creado_en)"),
            OpenApiParameter("page", OpenApiTypes.INT, OpenApiParameter.QUERY,
                             description="Número de página")
        ],
        responses={200: UsuarioSerializer(many=True)}
    ),
    retrieve=extend_schema(
        summary="Obtener un usuario",
        responses={200: UsuarioSerializer}
    ),
    create=extend_schema(
        summary="Crear usuario",
        responses={201: UsuarioSerializer},
        examples=[OpenApiExample("Ejemplo", value={
            "email": "user@ejemplo.com", "password": "****",
            "first_name": "Ada", "last_name": "Lovelace"
        })]
    ),
    update=extend_schema(summary="Reemplazar usuario", responses={200: UsuarioSerializer}),
    partial_update=extend_schema(summary="Actualizar parcialmente usuario", responses={200: UsuarioSerializer}),
    destroy=extend_schema(summary="Eliminar usuario", responses={204: OpenApiResponse(description="Sin contenido")}),
)
class UsuarioViewSet(viewsets.ModelViewSet):
    #permission_classes = [AllowAny]
    queryset = Usuario.objects.all().order_by("id")
    serializer_class = UsuarioSerializer
    permission_classes = [permissions.IsAuthenticated, IsSelfOrAdmin]
    # Doc/API fiel: habilitamos lo que documentamos arriba
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["email", "first_name", "last_name"]
    ordering_fields = ["id", "email", "first_name", "last_name", "creado_en"]


# ---------- Roles ----------
@extend_schema(tags=["Roles"])
@extend_schema_view(
    list=extend_schema(summary="Listar roles", responses={200: RolSerializer(many=True)}),
    retrieve=extend_schema(summary="Obtener rol", responses={200: RolSerializer}),
    create=extend_schema(summary="Crear rol", responses={201: RolSerializer}),
    update=extend_schema(summary="Reemplazar rol", responses={200: RolSerializer}),
    partial_update=extend_schema(summary="Actualizar parcialmente rol", responses={200: RolSerializer}),
    destroy=extend_schema(summary="Eliminar rol", responses={204: OpenApiResponse(description="Sin contenido")}),
)
class RolViewSet(viewsets.ModelViewSet):
    #permission_classes = [AllowAny]
    queryset = Rol.objects.all().order_by("id")
    serializer_class = RolSerializer
    permission_classes = [permissions.IsAuthenticated]



# ---------- Estudios ----------
@extend_schema(tags=["Estudios"])
@extend_schema_view(
    list=extend_schema(
        summary="Listar estudios",
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY,
                             description="Busca por nombre o CUIT"),
            OpenApiParameter("ordering", OpenApiTypes.STR, OpenApiParameter.QUERY,
                             description="Campo de orden (id, nombre, cuit, creado_en)"),
        ],
        responses={200: EstudioJuridicoSerializer(many=True)}
    ),
    retrieve=extend_schema(summary="Obtener estudio", responses={200: EstudioJuridicoSerializer}),
    create=extend_schema(summary="Crear estudio", responses={201: EstudioJuridicoSerializer}),
    update=extend_schema(summary="Reemplazar estudio", responses={200: EstudioJuridicoSerializer}),
    partial_update=extend_schema(summary="Actualizar parcialmente estudio", responses={200: EstudioJuridicoSerializer}),
    destroy=extend_schema(summary="Eliminar estudio", responses={204: OpenApiResponse(description="Sin contenido")}),
)
class EstudioJuridicoViewSet(viewsets.ModelViewSet):
    #permission_classes = [AllowAny]
    queryset = EstudioJuridico.objects.all().order_by("-id")
    serializer_class = EstudioJuridicoSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre", "cuit"]
    ordering_fields = ["id", "nombre", "cuit", "creado_en"]



# ---------- Filtros ----------
class EstudioUsuarioFilter(dj_filters.FilterSet):
    # /api/estudios-usuarios/?usuario=1&estudio=2&rol=3&vigente=true
    usuario = dj_filters.NumberFilter(field_name="usuario_id", lookup_expr="exact")
    estudio = dj_filters.NumberFilter(field_name="estudio_id", lookup_expr="exact")
    rol = dj_filters.NumberFilter(field_name="rol_id", lookup_expr="exact")
    vigente = dj_filters.BooleanFilter(field_name="vigente")

    # rangos de fechas: /api/estudios-usuarios/?fecha_alta_after=2025-01-01&fecha_alta_before=2025-12-31
    fecha_alta_after = dj_filters.DateFilter(field_name="fecha_alta", lookup_expr="gte")
    fecha_alta_before = dj_filters.DateFilter(field_name="fecha_alta", lookup_expr="lte")
    fecha_baja_after = dj_filters.DateFilter(field_name="fecha_baja", lookup_expr="gte")
    fecha_baja_before = dj_filters.DateFilter(field_name="fecha_baja", lookup_expr="lte")

    # null / no null: /api/estudios-usuarios/?sin_baja=1
    sin_baja = dj_filters.BooleanFilter(
        method="filter_sin_baja",
        help_text="true/1 solo registros sin fecha_baja; false/0 solo con fecha_baja"
    )

    def filter_sin_baja(self, queryset, name, value: bool):
        if value:
            return queryset.filter(fecha_baja__isnull=True)
        return queryset.filter(fecha_baja__isnull=False)

    class Meta:
        model = EstudioUsuario
        fields = ["usuario", "estudio", "rol", "vigente"]


# ---------- Membresías Estudio–Usuario ----------
@extend_schema(tags=["Estudios – Usuarios"])
@extend_schema_view(
    list=extend_schema(
        summary="Listar membresías",
        parameters=[
            OpenApiParameter("usuario", OpenApiTypes.INT, OpenApiParameter.QUERY, description="ID de usuario"),
            OpenApiParameter("estudio", OpenApiTypes.INT, OpenApiParameter.QUERY, description="ID de estudio"),
            OpenApiParameter("rol", OpenApiTypes.INT, OpenApiParameter.QUERY, description="ID de rol"),
            OpenApiParameter("vigente", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="true/false"),
            OpenApiParameter("fecha_alta_after", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="YYYY-MM-DD"),
            OpenApiParameter("fecha_alta_before", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="YYYY-MM-DD"),
            OpenApiParameter("fecha_baja_after", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="YYYY-MM-DD"),
            OpenApiParameter("fecha_baja_before", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="YYYY-MM-DD"),
            OpenApiParameter("sin_baja", OpenApiTypes.BOOL, OpenApiParameter.QUERY,
                             description="true=solo sin baja, false=solo con baja"),
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY,
                             description="Busca por usuario(email,nombre,apellido), estudio(nombre) o rol(nombre)"),
            OpenApiParameter("ordering", OpenApiTypes.STR, OpenApiParameter.QUERY,
                             description="Campos: id, fecha_alta, fecha_baja, vigente, usuario__email, estudio__nombre, rol__nombre"),
        ],
        responses={200: EstudioUsuarioSerializer(many=True)}
    ),
    retrieve=extend_schema(summary="Obtener membresía", responses={200: EstudioUsuarioSerializer}),
    create=extend_schema(summary="Crear membresía", responses={201: EstudioUsuarioSerializer}),
    update=extend_schema(summary="Reemplazar membresía", responses={200: EstudioUsuarioSerializer}),
    partial_update=extend_schema(summary="Actualizar parcialmente membresía", responses={200: EstudioUsuarioSerializer}),
    destroy=extend_schema(summary="Eliminar membresía", responses={204: OpenApiResponse(description="Sin contenido")}),
)
class EstudioUsuarioViewSet(viewsets.ModelViewSet):
    #permission_classes = [AllowAny]
    queryset = EstudioUsuario.objects.select_related("usuario","estudio","rol").all()
    serializer_class = EstudioUsuarioSerializer
    permission_classes = [permissions.IsAuthenticated]
    # filtros / búsqueda / orden
    filter_backends = [dj_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EstudioUsuarioFilter
    search_fields = [
        "usuario__email", "usuario__first_name", "usuario__last_name",
        "estudio__nombre", "rol__nombre",
    ]
    ordering_fields = [
        "id", "fecha_alta", "fecha_baja", "vigente",
        "usuario__email", "estudio__nombre", "rol__nombre",
    ]
    ordering = ["-id"]


# ---------- Health ----------
@extend_schema(
    tags=["Infra"],
    summary="Health check",
    description="Devuelve el estado del servicio",
    responses={200: HealthCheckSerializer},
    examples=[OpenApiExample("OK", value={"status": "ok"})],
)
class HealthCheckViewSet(ViewSet):
    permission_classes = [AllowAny]
    serializer_class = HealthCheckSerializer

    def list(self, request):
        return HttpResponse("OK", status=200)