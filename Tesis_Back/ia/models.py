from django.db import models
from django.conf import settings


class IALog(models.Model):
    """Registro de cada operación de IA ejecutada."""

    TASK_SUMMARIZE = "summarize"
    TASK_GRAMMAR = "grammar"
    TASK_CHOICES = [
        (TASK_SUMMARIZE, "Resumen"),
        (TASK_GRAMMAR, "Corrección gramatical"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    document = models.ForeignKey("causa.Documento", null=True, blank=True, on_delete=models.SET_NULL)
    task_type = models.CharField(max_length=20, choices=TASK_CHOICES)
    result = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # type: ignore[override]
        return f"{self.user} - {self.task_type} - {self.created_at:%Y-%m-%d}"
