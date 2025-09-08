from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
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
    causa = serializers.PrimaryKeyRelatedField(queryset=Causa.objects.all(), required=True)
    parte = serializers.PrimaryKeyRelatedField(queryset=Parte.objects.all(), required=True)
    #rol_parte = serializers.PrimaryKeyRelatedField(queryset=RolParte.objects.all(), required=False, allow_null=True)
    #observaciones = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = CausaParte
        # dejamos solo los campos necesarios
        fields = ["id", "causa", "parte"]
        extra_kwargs = {
            "causa": {"required": True},
            "parte": {"required": True},
        }


class CausaProfesionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = CausaProfesional
        fields = ["id", "causa", "profesional", "rol_profesional"]

class CausaGrafoSerializer(serializers.ModelSerializer):
    data = serializers.JSONField()  # <— ¡no read_only!

    class Meta:
        model = CausaGrafo
        fields = ["id", "causa", "data", "actualizado_en"]
        read_only_fields = ["id", "causa", "actualizado_en"]

    def update(self, instance, validated_data):
        # Sólo actualizamos el JSON del grafo
        if "data" in validated_data:
            instance.data = validated_data["data"]
        instance.save(update_fields=["data", "actualizado_en"])
        return instance


class CausaParteReadSerializer(serializers.ModelSerializer):
    # devolvemos el objeto parte completo
    parte = ParteSerializer(read_only=True)

    class Meta:
        model = CausaParte
        # devolvemos causa como ID y parte como objeto expandido
        fields = ("causa", "parte")

class CausaSerializer(serializers.ModelSerializer):
    partes = CausaParteReadSerializer(source="causa_partes", many=True, read_only=True)
    profesionales = CausaProfesionalSerializer(source="causa_profesionales", many=True, read_only=True)
    documentos = DocumentoSerializer(many=True, read_only=True)
    eventos = EventoProcesalSerializer(many=True, read_only=True)
    grafo = CausaGrafoSerializer(read_only=True)

    class Meta:
        model = Causa
        fields = [
            "id", "numero_expediente", "caratula", "fuero", "jurisdiccion",
            "fecha_inicio", "estado", "creado_en", "actualizado_en", "creado_por",
            "partes", "profesionales", "documentos", "eventos", "grafo"
        ]
        read_only_fields = ["id", "creado_en", "actualizado_en"]
        validators = [
            UniqueTogetherValidator(
                queryset=Causa.objects.all(),
                fields=("numero_expediente", "fuero", "jurisdiccion"),
                message="Los campos numero_expediente, fuero, jurisdiccion deben formar un conjunto único."
            )
        ]


class TimelineResponseSerializer(serializers.Serializer):
    causa = serializers.IntegerField()
    eventos = EventoProcesalSerializer(many=True)
    documentos = DocumentoSerializer(many=True, required=False)

class ProximosResponseSerializer(serializers.Serializer):
    desde = serializers.DateField()
    hasta = serializers.DateField()
    eventos = EventoProcesalSerializer(many=True)


