from django.db import models

# Create your models here.
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from django.utils.translation import gettext_lazy as _

# ----- Catálogos / auxiliares -----
class RolParte(models.Model):
    nombre = models.CharField(max_length=50, unique=True)  # actor, demandado, perito, testigo, etc.
    def __str__(self): return self.nombre

class Domicilio(models.Model):
    calle = models.CharField(max_length=120)
    numero = models.CharField(max_length=20, blank=True)
    ciudad = models.CharField(max_length=80, blank=True)
    provincia = models.CharField(max_length=80, blank=True)
    pais = models.CharField(max_length=80, default="Argentina")
    def __str__(self): return f"{self.calle} {self.numero}, {self.ciudad}"

class Parte(models.Model):
    FISICA, JURIDICA = "F", "J"
    TIPO_PERSONA_CHOICES = [(FISICA, "Física"), (JURIDICA, "Jurídica")]
    tipo_persona = models.CharField(max_length=1, choices=TIPO_PERSONA_CHOICES)
    nombre_razon_social = models.CharField(max_length=200)
    documento = models.CharField(max_length=30, blank=True)
    cuit_cuil = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    domicilio = models.ForeignKey(Domicilio, null=True, blank=True, on_delete=models.SET_NULL)
    def __str__(self): return self.nombre_razon_social

class Profesional(models.Model):
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    matricula = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    def __str__(self): return f"{self.apellido}, {self.nombre}"

# ----- Núcleo -----
class Causa(models.Model):
    numero_expediente = models.CharField(max_length=100, unique=True)
    caratula = models.CharField(max_length=250)
    fuero = models.CharField(max_length=100, blank=True)
    jurisdiccion = models.CharField(max_length=120, blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=60, blank=True)  # p.ej. 'en trámite', 'finalizada'
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="causas_creadas")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["numero_expediente"])]
    def __str__(self): return f"{self.numero_expediente} – {self.caratula}"

class CausaParte(models.Model):
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="partes")
    parte = models.ForeignKey(Parte, on_delete=models.CASCADE)
    rol_parte = models.ForeignKey(RolParte, on_delete=models.PROTECT)
    observaciones = models.TextField(blank=True)
    class Meta:
        unique_together = ("causa", "parte", "rol_parte")

class CausaProfesional(models.Model):
    PATROCINANTE, APODERADO, COLABORADOR = "patrocinante", "apoderado", "colaborador"
    ROLES = [(PATROCINANTE, "Patrocinante"), (APODERADO, "Apoderado"), (COLABORADOR, "Colaborador")]
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="profesionales")
    profesional = models.ForeignKey(Profesional, on_delete=models.CASCADE)
    rol_profesional = models.CharField(max_length=20, choices=ROLES)
    class Meta:
        unique_together = ("causa", "profesional", "rol_profesional")

class Documento(models.Model):
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="documentos")
    titulo = models.CharField(max_length=200)
    archivo = models.FileField(upload_to="documentos/")  # para dev; luego pasás a S3/Cloudinary
    fecha = models.DateField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

class EventoProcesal(models.Model):
    causa = models.ForeignKey(Causa, on_delete=models.CASCADE, related_name="eventos")
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    fecha = models.DateField()
    plazo_limite = models.DateField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["fecha", "id"]
