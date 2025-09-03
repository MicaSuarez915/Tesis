from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType

from .models import (Causa, Documento, EventoProcesal, Nodo, CausaParte, CausaProfesional, DocumentoEvento, Profesional, Parte)

def get_or_create_node(causa, instance_type, **kwargs):
    content_type = ContentType.objects.get_for_model(causa)
    node, created = Nodo.objects.get_or_create(
        causa=causa,
        content_type=content_type,
        defaults=kwargs
    )
    return node, created