from django.db import models

# Create your models here.
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from datetime import date
from django.utils import timezone


# ---------------------------
# Roles (admin, abogado, lector, etc.)
# ---------------------------
class Rol(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.nombre


# ---------------------------
# Custom User (email como login)
# ---------------------------
class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("El email es obligatorio")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser debe tener is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class Usuario(AbstractUser):
    """
    - Login por email (username no se usa).
    - Campos según tu diagrama: nombre, apellido, email(UNIQUE), hash_password (lo maneja Django), 
      matricula_id, telefono, creado_en, id_rol (global/por defecto).
    """
    username = None  # anulamos username
    email = models.EmailField(unique=True)

    # nombre / apellido los heredamos como first_name / last_name
    matricula_id = models.CharField(max_length=50, blank=True)
    telefono = models.CharField(max_length=30, blank=True, validators=[
        RegexValidator(r"^[0-9+\-() ]*$", "Formato de teléfono inválido")
    ])
    creado_en = models.DateTimeField(auto_now_add=True)

    # rol global (opcional). La autorización fina va por EstudioUsuario
    rol = models.ForeignKey(Rol, null=True, blank=True, on_delete=models.SET_NULL)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # no pedimos username

    objects = UsuarioManager()

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return f"{self.email}"


# ---------------------------
# Estudio Jurídico
# ---------------------------
class EstudioJuridico(models.Model):
    nombre = models.CharField(max_length=200)
    cuit = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=30, blank=True)
    pagina_web = models.URLField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Estudio jurídico"
        verbose_name_plural = "Estudios jurídicos"

    def __str__(self):
        return f"{self.nombre} ({self.cuit})"


# ---------------------------
# Relación Estudio–Usuario (estudio_usuario)
# ---------------------------
class EstudioUsuario(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membresias")
    estudio = models.ForeignKey(EstudioJuridico, on_delete=models.CASCADE, related_name="membresias")
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT)

    fecha_alta = models.DateField(default=date.today)
    fecha_baja = models.DateField(null=True, blank=True)
    vigente = models.BooleanField(default=True)

    # permisos: puede ser JSON (lista de scopes) o texto. Uso JSON para flexibilidad.
    permisos = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("usuario", "estudio", "rol")  # evita duplicados
        verbose_name = "Membresía de estudio"
        verbose_name_plural = "Membresías de estudio"

    def __str__(self):
        return f"{self.usuario.email} @ {self.estudio.nombre} [{self.rol}]"
