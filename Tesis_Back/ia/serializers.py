from rest_framework import serializers


class SummarizeSerializer(serializers.Serializer):
    """Datos de entrada para el resumen automático."""
    text = serializers.CharField(required=False, allow_blank=True)
    file = serializers.FileField(required=False)


class SummarizeResponseSerializer(serializers.Serializer):
    """Respuesta con el texto resumido."""
    summary = serializers.CharField()


class GrammarCheckSerializer(serializers.Serializer):
    """Datos de entrada para la corrección gramatical."""
    text = serializers.CharField()


class GrammarCheckResponseSerializer(serializers.Serializer):
    """Respuesta con el texto corregido."""
    corrected_text = serializers.CharField()
