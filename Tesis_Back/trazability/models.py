from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
import uuid

class Trazability(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    causa = models.OneToOneField(
        'causa.Causa', 
        on_delete=models.CASCADE, 
        related_name='trazability'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'trazability'
        verbose_name = 'Trazabilidad'
        verbose_name_plural = 'Trazabilidades'

    def __str__(self):
        return f"Trazabilidad de Causa {self.causa.numero_expediente}"

    def get_recent_moves(self, limit=10):
        """Retorna los últimos N movimientos"""
        return self.moves.all().order_by('-timestamp')[:limit]


class Move(models.Model):
    class MoveAction(models.TextChoices):
        CREATE = 'create', 'Crear'
        UPDATE = 'update', 'Actualizar'
        DELETE = 'delete', 'Eliminar'
        STATUS_CHANGE = 'status_change', 'Cambio de Estado'
        ADD = 'add', 'Agregar'
        REMOVE = 'remove', 'Remover'

    class MoveEntityType(models.TextChoices):
        CAUSA = 'causa', 'Causa'
        PARTE = 'parte', 'Parte'
        DOCUMENTO = 'documento', 'Documento'
        TASK = 'task', 'Tarea'
        EVENTO = 'evento', 'Evento Procesal'
        RESUMEN_IA = 'resumen_ia', 'Resumen IA'
        OTRO = 'otro', 'Otro'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trazability = models.ForeignKey(
        Trazability,
        on_delete=models.CASCADE,
        related_name='moves'
    )
    causa = models.ForeignKey(
        'causa.Causa',
        on_delete=models.CASCADE,
        related_name='trazability_moves'
    )
    user = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, related_name="trazability_moves")
    user_name = models.CharField(max_length=255, blank=True, default='')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    action = models.CharField(max_length=20, choices=MoveAction.choices)
    entity_type = models.CharField(max_length=20, choices=MoveEntityType.choices)
    
    previous_value = models.TextField(blank=True, default='')
    summary = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'move'
        verbose_name = 'Movimiento'
        verbose_name_plural = 'Movimientos'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['trazability', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.user_name} - {self.action} - {self.entity_type}"