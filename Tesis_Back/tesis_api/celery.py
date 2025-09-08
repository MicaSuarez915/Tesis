import os
from celery import Celery

# Nombre de tu settings de Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tesis_api.settings")

app = Celery("tesis_api")

# Lee configuración CELERY_* desde settings.py
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-descubre tasks.py en cada app
app.autodiscover_tasks()
