FROM python:3.11-slim
WORKDIR /app
COPY Tesis_Back/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY Tesis_Back /app
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
