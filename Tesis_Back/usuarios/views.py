from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions
from rest_framework.permissions import AllowAny
from .models import Usuario, Rol, EstudioJuridico, EstudioUsuario
from .serializers import (
    UsuarioSerializer, RolSerializer, EstudioJuridicoSerializer, EstudioUsuarioSerializer
)



class IsSelfOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Usuario):
            return request.user.is_staff or obj.id == request.user.id
        return request.user.is_staff or request.user.is_superuser

class UsuarioViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    queryset = Usuario.objects.all().order_by("id")
    serializer_class = UsuarioSerializer
    #permission_classes = [permissions.IsAuthenticated, IsSelfOrAdmin]

class RolViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    queryset = Rol.objects.all().order_by("id")
    serializer_class = RolSerializer
    #permission_classes = [permissions.IsAuthenticated]

class EstudioJuridicoViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    queryset = EstudioJuridico.objects.all().order_by("-id")
    serializer_class = EstudioJuridicoSerializer
    #permission_classes = [permissions.IsAuthenticated]

class EstudioUsuarioViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    queryset = EstudioUsuario.objects.select_related("usuario","estudio","rol").all()
    serializer_class = EstudioUsuarioSerializer
    #permission_classes = [permissions.IsAuthenticated]
