from django.contrib import admin
from .models import IALog

@admin.register(IALog)
class IALogAdmin(admin.ModelAdmin):
    """Administra los registros de IA."""
    list_display = ("user", "task_type", "created_at")
    list_filter = ("task_type", "created_at")
