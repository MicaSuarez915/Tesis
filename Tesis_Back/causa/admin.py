from django.contrib import admin

# Register your models here.
from .models import *

admin.site.register([RolParte, Domicilio, Parte, Profesional, Causa, CausaParte, CausaProfesional, Documento, EventoProcesal])
