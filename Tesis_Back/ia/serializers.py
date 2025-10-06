from rest_framework import serializers

from .models import SummaryRun, VerificationResult


class VerificationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationResult
        fields = ["verdict", "issues", "raw_output", "created_at"]


class SummaryRunSerializer(serializers.ModelSerializer):
    verification = VerificationResultSerializer(read_only=True)

    class Meta:
        model = SummaryRun
        fields = [
            "id", "causa", "topic", "filters", "db_snapshot", "prompt",
            "summary_text", "citations", "created_at", "created_by",
            "verification", "updated_at"
        ]
        read_only_fields = ["id", "db_snapshot", "prompt", "summary_text", "citations", "created_at", "created_by", "verification", "updated_at"]


# (opcional) para validar el POST de generación
class SummaryGenerateSerializer(serializers.Serializer):
    topic = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    filters = serializers.DictField(child=serializers.JSONField(), required=False, default=dict)


class GrammarCheckRequestSerializer(serializers.Serializer):
    # O uno u otro:
    text = serializers.CharField(required=False, allow_blank=False)
    documento_id = serializers.IntegerField(required=False)

    # Opcionales
    idioma = serializers.ChoiceField(choices=[("es", "Español"), ("auto", "Auto")], required=False, default="es")
    max_issues = serializers.IntegerField(required=False, min_value=1, default=200)

    def validate(self, data):
        if not data.get("text") and not data.get("documento_id"):
            raise serializers.ValidationError("Enviá 'text' o 'documento_id'.")
        return data


class GrammarIssueSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    line = serializers.IntegerField()
    original = serializers.CharField()
    corrected = serializers.CharField()
    category = serializers.CharField()
    explanation = serializers.CharField()


class GrammarCheckResponseSerializer(serializers.Serializer):
    issues = GrammarIssueSerializer(many=True)
    counts = serializers.DictField()  # {"total": X, "por_pagina": {"1": n1, "2": n2, ...}}
    meta = serializers.DictField()    # {"doc_type": "pdf|txt|docx", "pages": N, "truncated": bool}