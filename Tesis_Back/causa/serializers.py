from rest_framework import serializers
from .models import *

class DomicilioSerializer(serializers.ModelSerializer):
    class Meta: model = Domicilio; fields = "__all__"

class ParteSerializer(serializers.ModelSerializer):
    domicilio = DomicilioSerializer(required=False, allow_null=True)
    class Meta: model = Parte; fields = "__all__"

class RolParteSerializer(serializers.ModelSerializer):
    class Meta: model = RolParte; fields = "__all__"

class ProfesionalSerializer(serializers.ModelSerializer):
    class Meta: model = Profesional; fields = "__all__"

class DocumentoSerializer(serializers.ModelSerializer):
    class Meta: model = Documento; fields = "__all__"

class EventoProcesalSerializer(serializers.ModelSerializer):
    class Meta: model = EventoProcesal; fields = "__all__"

class CausaParteSerializer(serializers.ModelSerializer):
    class Meta: model = CausaParte; fields = "__all__"

class CausaProfesionalSerializer(serializers.ModelSerializer):
    class Meta: model = CausaProfesional; fields = "__all__"

class CausaSerializer(serializers.ModelSerializer):
    partes = CausaParteSerializer(many=True, read_only=True)
    profesionales = CausaProfesionalSerializer(many=True, read_only=True)
    documentos = DocumentoSerializer(many=True, read_only=True)
    eventos = EventoProcesalSerializer(many=True, read_only=True)

    class Meta:
        model = Causa
        fields = "__all__"
        read_only_fields = ["creado_en", "actualizado_en"]
