from rest_framework import serializers
from .models import SummaryRun, VerificationResult, Message, Conversation

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
    issues = serializers.ListField()
    counts = serializers.DictField()
    meta = serializers.DictField()
    corrected_text = serializers.CharField()        
    corrected_pages = serializers.ListField()       


class MessageSerializer(serializers.ModelSerializer):
    attachments = serializers.JSONField(required=False)
    class Meta:
        model = Message
        fields = ("id", "role", "content", "created_at", "attachments")
        read_only_fields = fields

class ConversationListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ("id", "title", "created_at", "updated_at", "last_message_at")
        read_only_fields = fields




class ConversationCreateRequestSerializer(serializers.Serializer):
    first_message = serializers.CharField()
    title = serializers.CharField(required=False, allow_blank=True)

class ConversationMessageCreateRequestSerializer(serializers.Serializer):
    content = serializers.CharField()
    attachments = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_empty=True
    )
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

# Response (solo los mensajes nuevos)
class ConversationMessageCreateResponseSerializer(serializers.Serializer):
    messages = MessageSerializer(many=True)


class AskJurisFiltersSerializer(serializers.Serializer):
    tribunal = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    desde = serializers.DateField(required=False, allow_null=True)
    hasta = serializers.DateField(required=False, allow_null=True)

class AskJurisRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    strict = serializers.BooleanField(required=False, default=True)
    debug = serializers.BooleanField(required=False, default=False)
    filters = AskJurisFiltersSerializer(required=False)

class CitationSerializer(serializers.Serializer):
    id = serializers.CharField()
    titulo = serializers.CharField()
    tribunal = serializers.CharField(allow_null=True, required=False)
    fecha = serializers.DateField(allow_null=True, required=False)
    url = serializers.URLField(required=False, allow_blank=True)
    score = serializers.FloatField()

class AskJurisResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    answer = serializers.CharField()
    citations = CitationSerializer(many=True)
    debug = serializers.JSONField(required=False)



class AttachmentSerializer(serializers.Serializer):
    # Podés extender según tus necesidades (url, s3_key, filename, content_type, etc.)
    url = serializers.URLField(required=False, allow_blank=False)
    s3_key = serializers.CharField(required=False, allow_blank=False)
    filename = serializers.CharField(required=False, allow_blank=True)
    content_type = serializers.CharField(required=False, allow_blank=True)

class StartConversationSerializer(serializers.Serializer):
    first_message = serializers.CharField()
    title = serializers.CharField(required=False, allow_blank=True)
    open_ia = serializers.CharField(required=False, allow_blank=True)  # "true"/"false" (string)

class ContinueConversationSerializer(serializers.Serializer):
    content = serializers.CharField()
    attachments = AttachmentSerializer(many=True, required=False)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

class AskJurisRequestUnionSerializer(serializers.Serializer):
    """
    Acepta **o** el shape de inicio de conversación **o** el de continuación.
    """
    # Campos opcionales; validamos lógicamente en validate()
    first_message = serializers.CharField(required=False)
    title = serializers.CharField(required=False, allow_blank=True)
    open_ia = serializers.CharField(required=False, allow_blank=True)

    content = serializers.CharField(required=False)
    attachments = AttachmentSerializer(many=True, required=False)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    conversation_id = serializers.CharField(required=False, allow_blank=True)
    title = serializers.CharField(required=False, allow_blank=True)


    # Filtros opcionales (compatibilidad con tu pipeline)
    strict = serializers.BooleanField(required=False, default=True)
    debug = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        has_first = "first_message" in attrs
        has_content = "content" in attrs
        if has_first and has_content:
            raise serializers.ValidationError("No podés enviar 'first_message' y 'content' a la vez.")
        if not has_first and not has_content:
            raise serializers.ValidationError("Debés enviar 'first_message' (inicio) o 'content' (continuación).")

        attrs["__query__"] = attrs.get("first_message") or attrs.get("content")

        # Normalización de conversation_id
        if has_first and attrs.get("conversation_id"):
            # Podrías permitir “reanudar” si existe; si preferís forzar nuevo, limpiá:
            pass

        return attrs

# --------------------------- Serializers de salida ----------------------------

class AssistantCitationSerializer(serializers.Serializer):
    titulo = serializers.CharField()
    url = serializers.CharField()

class ConversationMessageSerializer(serializers.Serializer):
    id = serializers.CharField()
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField()
    created_at = serializers.DateTimeField()  # ISO8601 con Z
    citations = AssistantCitationSerializer(many=True, required=False)

class ConversationResponseSerializer(serializers.Serializer):
    id = serializers.CharField()  # ← ESTO FALTABA
    title = serializers.CharField()  # ← ESTO TAMBIÉN
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    last_message_at = serializers.DateTimeField()
    messages = ConversationMessageSerializer(many=True)


class ConversationListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ("id", "title", "created_at", "updated_at", "last_message_at")

class ConversationMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ("id", "role", "content", "created_at", "citations")

class ConversationDetailSerializer(serializers.ModelSerializer):
    messages = ConversationMessageSerializer(many=True)

    class Meta:
        model = Conversation
        fields = ("id", "title", "created_at", "updated_at", "last_message_at", "messages")