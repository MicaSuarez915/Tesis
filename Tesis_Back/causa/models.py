from django.db import models

# Create your models here.
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.db.models import Q
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField  # opcional si querés arrays tipados

from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_delete
from django.dispatch import receiver

# ----- Catálogos / auxiliares -----
class RolParte(models.Model):
    nombre = models.CharField(max_length=50, unique=True)  # actor, demandado, perito, testigo, etc.
    def __str__(self): return self.nombre

class Domicilio(models.Model):
    calle = models.CharField(max_length=120, blank=True, default="")
    numero = models.CharField(max_length=20, blank=True, default="")
    ciudad = models.CharField(max_length=80, blank=True, default="")
    provincia = models.CharField(max_length=80, blank=True, default="")
    pais = models.CharField(max_length=80, default="Argentina")
    def __str__(self): return f"{self.calle} {self.numero}, {self.ciudad}"

class Parte(models.Model):
    FISICA, JURIDICA = "F", "J"
    TIPO_PERSONA_CHOICES = [(FISICA, "Física"), (JURIDICA, "Jurídica")]
    tipo_persona = models.CharField(max_length=1, choices=TIPO_PERSONA_CHOICES)
    nombre_razon_social = models.CharField(max_length=200)
    documento = models.CharField(max_length=30, blank=True, default="", null=True)
    cuit_cuil = models.CharField(max_length=20, blank=True, default="", null=True)
    email = models.EmailField(blank=True, default="")
    telefono = models.CharField(max_length=30, blank=True, default="")
    domicilio = models.CharField(max_length=250, blank=True, default="")
    class Meta:
        indexes = [models.Index(fields=["nombre_razon_social"]),
                   models.Index(fields=["documento"]),
                   models.Index(fields=["cuit_cuil"])]
    def __str__(self): return self.nombre_razon_social

class Profesional(models.Model):
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    matricula = models.CharField(max_length=50, unique=True, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    telefono = models.CharField(max_length=30, blank=True, default="")
    class Meta:
        indexes = [models.Index(fields=["apellido", "nombre"]),
                   models.Index(fields=["matricula"])]
    def __str__(self): return f"{self.apellido}, {self.nombre}"

# ----- Núcleo -----
class Causa(models.Model):
    numero_expediente = models.CharField(max_length=100, db_index=True)
    caratula = models.CharField(max_length=250)
    fuero = models.CharField(max_length=100, blank=True, db_index=True)
    jurisdiccion = models.CharField(max_length=120, blank=True, db_index=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    ESTADOS = (
        ("abierta", "Abierta"),
        ("en_tramite", "En trámite"),
        ("con_sentencia", "Con sentencia"),
        ("cerrada", "Cerrada"),
        ("archivada", "Archivada"),
    )
    estado = models.CharField(max_length=60, blank=True, choices=ESTADOS, default="abierta", db_index=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="causas_creadas")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    #agregar campo extra DESCRIPCIÓN OPCIONAL

    class Meta:
         # Un expediente no debería repetirse en el mismo fuero+jurisdicción
        constraints = [
            models.UniqueConstraint(
                fields=["numero_expediente", "fuero", "jurisdiccion"],
                name="uniq_expediente_fuero_jurisdiccion",
            )
        ]
        indexes = [
            models.Index(fields=["creado_en"]),
            models.Index(fields=["actualizado_en"]),
        ]
        ordering = ["-id"]
    def __str__(self): return f"{self.numero_expediente} – {self.caratula}"

class CausaParte(models.Model):
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="partes")
    parte = models.ForeignKey(Parte, on_delete=models.CASCADE, related_name="en_causas")
    rol_parte = models.ForeignKey(RolParte, on_delete=models.PROTECT, blank=True, null=True)
    observaciones = models.TextField(blank=True, default="")
    class Meta:
        # Evita repetir misma parte/rol en una causa
        constraints = [
            models.UniqueConstraint(fields=["causa", "parte", "rol_parte"],
                                    name="uniq_causa_parte_rol")
        ]
        indexes = [models.Index(fields=["causa", "rol_parte"])]

class CausaProfesional(models.Model):
    PATROCINANTE, APODERADO, COLABORADOR = "patrocinante", "apoderado", "colaborador"
    ROLES = [(PATROCINANTE, "Patrocinante"), (APODERADO, "Apoderado"), (COLABORADOR, "Colaborador")]
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="profesionales")
    profesional = models.ForeignKey(Profesional, on_delete=models.PROTECT, related_name="en_causas")
    rol_profesional = models.CharField(max_length=20, choices=ROLES)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["causa", "profesional", "rol_profesional"],
                                    name="uniq_causa_profesional_rol")
        ]
        indexes = [models.Index(fields=["causa", "rol_profesional"])]


def documento_upload_to(instance, filename):
    causa_id = instance.causa.id if instance.causa else 'sin_causa'
    return f"usuarios/{instance.usuario.id}/causas/{causa_id}/docs/{filename}"

class Documento(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documentos")
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="documentos")
    titulo = models.CharField(max_length=200)
    archivo = models.FileField(upload_to=documento_upload_to)  
    descripcion = models.TextField(blank=True, default="")
    creado_en = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=["causa"]),
                   models.Index(fields=["creado_en"])]

# Mover el receiver fuera de la clase Documento
@receiver(post_delete, sender=Documento)
def eliminar_archivo_s3(sender, instance, **kwargs):
    """
    Se asegura de que el archivo en S3 se borre cuando se elimina 
    un objeto Documento.
    """
    # El 'save=False' es importante para no re-guardar el modelo
    # que ya está siendo eliminado.
    if instance.archivo:
        instance.archivo.delete(save=False)

class EventoProcesal(models.Model):
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="eventos")
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, default="")
    fecha = models.DateField()
    plazo_limite = models.DateField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [
            models.Index(fields=["fecha"]),
            models.Index(fields=["plazo_limite"]),
            models.Index(fields=["causa", "fecha"]),
        ]
        ordering = ["fecha", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(plazo_limite__isnull=True) | Q(plazo_limite__gte=models.F("fecha")),
                name="chk_plazo_no_anterior_a_fecha",
            )
        ]



class DocumentoEvento(models.Model):
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name="en_eventos")
    evento = models.ForeignKey(EventoProcesal, on_delete=models.CASCADE, related_name="documentos_adjuntos")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["documento", "evento"], name="uniq_doc_evento")
        ]



class CausaGrafo(models.Model):
    causa = models.OneToOneField("Causa", on_delete=models.CASCADE, related_name="grafo")
    data = models.JSONField(default=dict, blank=True)   # acá vive el JSON entero (nodes/edges/lo que sea)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Grafo de causa #{self.causa_id}"