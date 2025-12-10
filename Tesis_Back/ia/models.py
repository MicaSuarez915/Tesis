import uuid
from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from django.db.models import JSONField


class SummaryRun(models.Model):
    topic = models.CharField(max_length=255, db_index=True)
    causa = models.ForeignKey(
        "causa.Causa", on_delete=models.CASCADE, related_name="summary_runs", db_index=True, null=True, blank=True
    )
    filters = models.JSONField(default=dict, blank=True)
    db_snapshot = models.JSONField(default=dict, blank=True)
    prompt = models.TextField(blank=True, default="")
    summary_text = models.TextField()
    citations = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="summary_runs"
    )

    class Meta:
        ordering = ["-updated_at", "-created_at"]

class VerificationResult(models.Model):
    VERDICT_OK = "ok"
    VERDICT_WARNING = "warning"
    VERDICT_FAIL = "fail"
    summary_run = models.OneToOneField(
        SummaryRun, on_delete=models.CASCADE, related_name="verification"
    )
    verdict = models.CharField(max_length=16, default=VERDICT_WARNING)
    issues = models.JSONField(default=list, blank=True)
    raw_output = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]




from pgvector.django import VectorField

class JurisDocument(models.Model):
    doc_id = models.CharField(max_length=128, unique=True)
    titulo = models.TextField()
    fuero = models.CharField(max_length=64)
    jurisdiccion = models.CharField(max_length=128)
    tribunal = models.TextField(blank=True, null=True)
    fecha = models.DateField(blank=True, null=True)
    link_origen = models.TextField(blank=True, null=True)
    s3_key_metadata = models.TextField(blank=True, null=True)
    s3_key_document = models.TextField(blank=True, null=True)
    mime_type = models.CharField(max_length=64, blank=True, null=True)
    length_tokens = models.IntegerField(blank=True, null=True)
    checksum = models.CharField(max_length=128, blank=True, null=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

class JurisChunk(models.Model):
    doc = models.ForeignKey(
        JurisDocument, to_field="doc_id", db_column="doc_id",
        related_name="chunks", on_delete=models.CASCADE
    )
    chunk_id = models.IntegerField()
    section = models.CharField(max_length=64, blank=True, null=True)
    text = models.TextField()
    span_start = models.IntegerField(blank=True, null=True)
    span_end = models.IntegerField(blank=True, null=True)
    tokens = models.IntegerField(blank=True, null=True)
    embedding = VectorField(dimensions=1536)  

    class Meta:
        unique_together = (("doc", "chunk_id"),)


def gen_conv_id() -> str:
    return f"c_{uuid.uuid4().hex[:12]}"

def gen_msg_id() -> str:
    return f"m_{uuid.uuid4().hex[:12]}"

#agregar 
class Conversation(models.Model):
    id = models.CharField(
        primary_key=True,
        max_length=64,
        default=gen_conv_id,   # <- ANTES: lambda
        editable=False,
    )
    title = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    last_message_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="conversations",
        on_delete=models.CASCADE,
        null=True,  # dejar null=True para poder migrar sin data migration
        blank=True,
    )
    open_ai=models.BooleanField(default=False)
    causa = models.ForeignKey(
        "causa.Causa", on_delete=models.CASCADE, related_name="conversations", null=True, blank=True
    )

    class Meta:
        ordering = ["-last_message_at"]
        indexes = [
            models.Index(fields=["user", "updated_at"]),
        ]

    def __str__(self):
        return f"{self.pk} - {self.title or '(sin título)'}"

    def touch(self):
        now = timezone.now()
        self.updated_at = now
        self.last_message_at = now
        self.save(update_fields=["updated_at", "last_message_at"])

class Message(models.Model):
    ROLE_CHOICES = (("user", "user"), ("assistant", "assistant"))

    id = models.CharField(
        primary_key=True,
        max_length=64,
        default=gen_msg_id,    # <- ANTES: lambda
        editable=False,
    )
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    # Si usás Django 3.1+ conviene:
    # attachments = models.JSONField(null=True, blank=True)
    # Si estabas usando el import viejo de postgres:
    from django.db.models import JSONField as _JSONField  # quita esto si usas models.JSONField
    attachments = _JSONField(null=True, blank=True)
    citations = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "ia_message"
        indexes = [models.Index(fields=["conversation", "created_at"])]

class IdempotencyKey(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="idempotency_keys")
    key = models.CharField(max_length=128)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "ia_idempotency_key"
        unique_together = (("conversation", "key"),)