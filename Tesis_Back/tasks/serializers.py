from rest_framework import serializers
from .models import Task

class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            'id',
            'causa',
            'content',
            'status',
            'priority',
            'deadline_date',
            'created_at',
            'updated_at',
            'completed_at',
            'order'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'completed_at']
    
    def to_representation(self, instance):
        """Formatear fechas en ISO format"""
        data = super().to_representation(instance)
        
        # Convertir deadline_date a formato "YYYY-MM-DD" si existe
        if data.get('deadline_date'):
            data['deadline_date'] = str(data['deadline_date'])
        
        return data