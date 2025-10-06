from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models
from django.utils import timezone


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
