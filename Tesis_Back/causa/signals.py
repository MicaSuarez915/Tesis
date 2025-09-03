from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Causa, Documento, EventoProcesal, CausaParte, CausaProfesional, CausaGrafo
from .utils import generar_grafo_desde_bd

def ensure_grafo(causa):
    grafo, created = CausaGrafo.objects.get_or_create(causa=causa)
    if created or not grafo.data:
        grafo.data = generar_grafo_desde_bd(causa)
        grafo.save(update_fields=["data", "actualizado_en"])

@receiver(post_save, sender=Documento)
@receiver(post_save, sender=EventoProcesal)
@receiver(post_save, sender=CausaParte)
@receiver(post_save, sender=CausaProfesional)
def bootstrap_grafo(sender, instance, created, **kwargs):
    if created:
        ensure_grafo(instance.causa)
@receiver(post_save, sender=Causa)
def bootstrap_grafo_causa(sender, instance, created, **kwargs):
    if created:
        ensure_grafo(instance)