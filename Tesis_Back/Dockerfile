# 1. Imagen base: Usamos una imagen oficial y ligera de Python.
FROM python:3.11-slim

# 2. Variables de entorno: Buenas prácticas para Python en contenedores.
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Directorio de trabajo: Creamos una carpeta /app y trabajaremos desde ahí.
WORKDIR /app

# 4. Instalar dependencias: Copiamos solo el archivo de requisitos primero
#    y lo instalamos. Docker usará el caché para este paso si no cambia.
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiar el código: Ahora copiamos todo el código de tu proyecto.
COPY . /app/

# 6. Exponer el puerto: Le decimos a Docker que nuestra app escuchará en el puerto 8000.
EXPOSE 8000

# 7. Comando de ejecución: Usamos Gunicorn, un servidor WSGI de producción,
#    para correr la aplicación.
CMD ["gunicorn", "tesis_api.wsgi:application", "--bind", "0.0.0.0:8000"]