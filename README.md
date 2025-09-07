# Tesis

## Módulo de IA legal

Este proyecto integra un módulo de IA para resumir documentos legales y corregir textos.

### Ejecución con Docker

1. Crear el archivo `Tesis_Back/.env` con las variables de configuración necesarias (credenciales de base de datos, claves, etc.).
2. Levantar los servicios:

   ```bash
   docker-compose up --build
   ```

Esto iniciará Django, PostgreSQL, Redis y el worker de Celery.

### Endpoints

- `POST /api/ia/summarize/` recibe `text` o un archivo `file` y devuelve `summary`.
- `POST /api/ia/grammar-check/` recibe `text` y devuelve `corrected_text`.

Ambos endpoints requieren autenticación mediante tokens de Django.
