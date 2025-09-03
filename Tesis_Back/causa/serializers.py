from rest_framework import serializers
from .models import *

class DomicilioSerializer(serializers.ModelSerializer):
    class Meta: model = Domicilio; fields = "__all__"

class ParteSerializer(serializers.ModelSerializer):
    domicilio = DomicilioSerializer(read_only=True)
    domicilio_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    class Meta: model = Parte; fields = "__all__"

class RolParteSerializer(serializers.ModelSerializer):
    class Meta: model = RolParte; fields = "__all__"

class ProfesionalSerializer(serializers.ModelSerializer):
    class Meta: model = Profesional; fields = "__all__"

class DocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Documento
        fields = ["id", "titulo", "archivo", "fecha", "creado_en", "causa"]
        read_only_fields = ["id", "creado_en"]

class EventoProcesalSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventoProcesal
        fields = ["id", "titulo", "descripcion", "fecha", "plazo_limite", "creado_en", "causa"]
        read_only_fields = ["id", "creado_en"]

class CausaParteSerializer(serializers.ModelSerializer):
    parte = ParteSerializer(read_only=True)
    #rol_parte = RolParteSerializer(read_only=True)
    class Meta:
        model = CausaParte
        fields = ["parte"]

class CausaProfesionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = CausaProfesional
        fields = ["id", "causa", "profesional", "rol_profesional"]

class CausaSerializer(serializers.ModelSerializer):
    partes = CausaParteSerializer(source="causa_partes", many=True, read_only=True)
    profesionales = CausaProfesionalSerializer(source="causa_profesionales", many=True, read_only=True)
    documentos = DocumentoSerializer(many=True, read_only=True)
    eventos = EventoProcesalSerializer(many=True, read_only=True)

    class Meta:
        model = Causa
        fields = [
            "id", "numero_expediente", "caratula", "fuero", "jurisdiccion",
            "fecha_inicio", "estado", "creado_en", "actualizado_en", "creado_por",
            "partes", "profesionales", "documentos", "eventos",
        ]
        read_only_fields = ["id", "creado_en", "actualizado_en"]


class TimelineResponseSerializer(serializers.Serializer):
    causa = serializers.IntegerField()
    eventos = EventoProcesalSerializer(many=True)
    documentos = DocumentoSerializer(many=True, required=False)

class ProximosResponseSerializer(serializers.Serializer):
    desde = serializers.DateField()
    hasta = serializers.DateField()
    eventos = EventoProcesalSerializer(many=True)