from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from .models import Task
from causa.models import Causa
from .serializers import TaskSerializer
from django.db import models
from trazability.trazabilityHelper import TrazabilityHelper 

class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Filtra tasks para que el usuario solo vea las de sus causas
        """
        user = self.request.user
        
        # Obtener IDs de causas creadas por el usuario
        user_causas = Causa.objects.filter(creado_por=user).values_list('id', flat=True)
        
        # Filtrar tasks que pertenecen a esas causas O tasks sin causa (null)
        queryset = Task.objects.filter(
            models.Q(causa_id__in=user_causas) | models.Q(causa__isnull=True)
        )
        
        return queryset
    
    @extend_schema(
        summary="Listar tasks de una causa",
        description="Obtiene todas las tasks asociadas a una causa específica del usuario autenticado",
        parameters=[
            OpenApiParameter(
                name='causa_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description='ID de la causa'
            )
        ],
        responses={200: TaskSerializer(many=True)},
        tags=['Tasks']
    )
    def list(self, request, causa_id=None):
        """
        GET /api/tasks/{causa_id}
        """
        if causa_id:
            # Verificar que la causa fue creada por el usuario
            causa = get_object_or_404(Causa, id=causa_id, creado_por=request.user)
            
            tasks = Task.objects.filter(causa_id=causa_id)
            serializer = self.get_serializer(tasks, many=True)
            return Response(serializer.data)
        
        # Listar todas las tasks del usuario (de sus causas)
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def perform_create(self, serializer):
        """
        Crea la task y registra en trazabilidad
        """
        task = serializer.save()
        
        # ✅ Registrar en trazabilidad solo si tiene causa asociada
        if task.causa:
            TrazabilityHelper.register_task_create(
                causa=task.causa,
                user=self.request.user,
                task_title=task.content,
                priority=task.get_priority_display()
            )
    
    @extend_schema(
        summary="Crear una nueva task",
        description="Crea una task. Si no se especifica causa, queda como task general (sin causa).",
        request=TaskSerializer,
        responses={201: TaskSerializer},
        examples=[
            OpenApiExample(
                'Ejemplo básico',
                value={
                    "content": "Llamar al perito",
                    "priority": "medium",
                    "deadline_date": "2025-01-20",
                    "causa": 12
                },
                request_only=True
            ),
            OpenApiExample(
                'Task general (sin causa)',
                value={
                    "content": "Revisar correos pendientes",
                    "priority": "low",
                    "deadline_date": "2025-01-15"
                },
                request_only=True
            )
        ],
        tags=['Tasks']
    )
    def create(self, request):
        """
        POST /api/tasks/
        """
        causa_id = request.data.get('causa')
        
        # Si viene causa, verificar que fue creada por el usuario
        if causa_id:
            causa = get_object_or_404(Causa, id=causa_id, creado_por=request.user)
            
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Obtener una task específica",
        description="Retorna los detalles de una task por su ID (solo si pertenece a una causa del usuario)",
        parameters=[
            OpenApiParameter(
                name='pk',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='ID de la task (formato: t_xxxxxxxxxxxx)'
            )
        ],
        responses={200: TaskSerializer},
        tags=['Tasks']
    )
    def retrieve(self, request, pk=None):
        """
        GET /api/tasks/{task_id}/
        """
        task = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = self.get_serializer(task)
        return Response(serializer.data)
    
    def perform_update(self, serializer):
        """
        Actualiza la task y registra cambios en trazabilidad
        """
        task = self.get_object()
        
        # Capturar valores anteriores
        old_content = task.content
        old_status = task.status_on_display(task.status)
        old_priority = task.priority_on_display(task.priority)
        old_deadline = task.deadline_date
        
        # Guardar actualización
        task = serializer.save()
        
        # ✅ Registrar cambios solo si tiene causa
        if task.causa:
            # Cambio de estado (especialmente cuando se completa)
            if old_status != task.get_status_display():
                if task.status == 'done':
                    TrazabilityHelper.register_task_complete(
                        causa=task.causa,
                        user=self.request.user,
                        task_title=task.content
                    )
                else:
                    TrazabilityHelper.register_task_update(
                        causa=task.causa,
                        user=self.request.user,
                        task_title=task.content,
                        field_name='estado',
                        old_value=old_status,
                        new_value=task.get_status_display()
                    )
            
            # Cambio de contenido
            if old_content != task.content:
                TrazabilityHelper.register_task_update(
                    causa=task.causa,
                    user=self.request.user,
                    task_title=old_content,
                    field_name='contenido',
                    old_value=old_content[:50] + '...' if len(old_content) > 50 else old_content,
                    new_value=task.content[:50] + '...' if len(task.content) > 50 else task.content
                )
            
            # Cambio de prioridad
            if old_priority != task.priority:
                TrazabilityHelper.register_task_update(
                    causa=task.causa,
                    user=self.request.user,
                    task_title=task.content,
                    field_name='prioridad',
                    old_value=old_priority,
                    new_value=task.priority_on_display(task.priority)
                )
            
            # Cambio de deadline
            if old_deadline != task.deadline_date:
                old_deadline_str = str(old_deadline) if old_deadline else 'Sin fecha límite'
                new_deadline_str = str(task.deadline_date) if task.deadline_date else 'Sin fecha límite'
                TrazabilityHelper.register_task_update(
                    causa=task.causa,
                    user=self.request.user,
                    task_title=task.content,
                    field_name='fecha límite',
                    old_value=old_deadline_str,
                    new_value=new_deadline_str
                )
    
    @extend_schema(
        summary="Actualizar parcialmente una task",
        description="Permite actualizar uno o más campos de la task (ej: marcar como done, cambiar contenido, etc)",
        parameters=[
            OpenApiParameter(
                name='pk',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='ID de la task'
            )
        ],
        request=TaskSerializer,
        responses={200: TaskSerializer},
        examples=[
            OpenApiExample(
                'Marcar como completada',
                value={"status": "done"},
                request_only=True
            ),
            OpenApiExample(
                'Cambiar contenido y prioridad',
                value={
                    "content": "Redactar demanda inicial y revisar prueba documental",
                    "priority": "high"
                },
                request_only=True
            )
        ],
        tags=['Tasks']
    )
    def partial_update(self, request, pk=None):
        """
        PATCH /api/tasks/{task_id}/
        """
        task = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Si intentan cambiar la causa, validar que la nueva causa también fue creada por el usuario
        if 'causa' in request.data and request.data['causa']:
            nueva_causa = get_object_or_404(Causa, id=request.data['causa'], creado_por=request.user)
        
        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        return Response(serializer.data)
    
    def perform_destroy(self, instance):
        """
        Elimina la task y registra en trazabilidad
        """
        # ✅ Registrar eliminación ANTES de borrar (solo si tiene causa)
        if instance.causa:
            TrazabilityHelper.register_task_delete(
                causa=instance.causa,
                user=self.request.user,
                task_title=instance.content
            )
        
        # Eliminar la task
        instance.delete()
    
    @extend_schema(
        summary="Eliminar una task",
        description="Elimina permanentemente una task (solo si pertenece a una causa del usuario)",
        parameters=[
            OpenApiParameter(
                name='pk',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='ID de la task'
            )
        ],
        responses={204: None},
        tags=['Tasks']
    )
    def destroy(self, request, pk=None):
        """
        DELETE /api/tasks/{task_id}/
        """
        task = get_object_or_404(self.get_queryset(), pk=pk)
        self.perform_destroy(task)
        return Response(status=status.HTTP_204_NO_CONTENT)