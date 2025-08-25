from django.contrib import admin

# Register your models here.
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import Usuario, Rol, EstudioJuridico, EstudioUsuario

@admin.register(Usuario)
class UsuarioAdmin(DjangoUserAdmin):
    model = Usuario
    list_display = ("email", "first_name", "last_name", "rol", "is_active", "is_staff")
    ordering = ("email",)
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Datos personales", {"fields": ("first_name", "last_name", "matricula_id", "telefono", "rol")}),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )

admin.site.register(Rol)
admin.site.register(EstudioJuridico)
admin.site.register(EstudioUsuario)