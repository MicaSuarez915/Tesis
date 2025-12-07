from django.shortcuts import render

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import Trazability, Move
from .serializers import TrazabilitySerializer, TrazabilityDetailSerializer, MoveSerializer

class TrazabilityViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para consultar trazabilidad
    Solo lectura - los Moves se crean automáticamente via signals/helpers
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TrazabilityDetailSerializer
    
    def get_queryset(self):
        return Trazability.objects.filter(
            causa__creado_por=self.request.user  # ✅ Cambiar 'user' por 'creado_por'
        ).prefetch_related('moves', 'moves__user')

    def retrieve(self, request, pk=None):
        """
        GET /api/trazability/{trazabilityId}/
        Retorna todo el historial de movimientos
        """
        trazability = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = self.get_serializer(trazability)
        return Response(serializer.data)
