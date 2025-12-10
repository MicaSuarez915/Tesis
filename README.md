# Tesis
# LexGO - Sistema de Gestión Legal Inteligente

Sistema integral de gestión de casos legales diseñado para asistir a abogados de temprana carrera en la Provincia de Buenos Aires, Argentina. Desarrollado como Proyecto de Tesis en la Universidad Argentina de la Empresa (UADE).

## 📋 Descripción

LexGO es una plataforma web que combina gestión de casos legales con capacidades de inteligencia artificial para:

- **Gestión de casos**: Organización completa de expedientes, documentos y procedimientos legales
- **Procesamiento inteligente de documentos**: Extracción automática de información con AWS Textract y OpenAI
- **Búsqueda de jurisprudencia**: Sistema de búsqueda semántica con embeddings vectoriales (pgvector)
- **Asistente de IA**: Análisis contextual de documentos y consultas legales con GPT-4
- **Clasificación automática**: Machine Learning para sugerir estructuras de casos y detectar etapas procesales
- **Trazabilidad completa**: Auditoría de todas las acciones sobre casos y documentos

## 🏗️ Arquitectura

### Stack Tecnológico

**Backend:**
- Django 5.2.5 + Django REST Framework
- PostgreSQL 16 con extensión pgvector
- Gunicorn como servidor WSGI

**IA/ML:**
- OpenAI GPT-4 / GPT-4-mini
- OpenAI Embeddings (text-embedding-3-small)
- AWS Textract para OCR
- scikit-learn para clasificación

**Infraestructura:**
- AWS EC2 (Amazon Linux 2023)
- AWS RDS PostgreSQL
- AWS S3 para almacenamiento de documentos
- Application Load Balancer
- Terraform para IaC

## 🚀 Deployment

### Prerrequisitos

- AWS Account (Student Lab o cuenta regular)
- Terraform >= 1.0
- Python 3.11+
- Node.js (para frontend)
- OpenAI API Key

### Variables de Entorno

Crear archivo `.env` con:
```env
# Django
SECRET_KEY=your-secret-key
DEBUG=False
ALLOWED_HOSTS=.ngrok-free.app,localhost,your-domain.com

# Database
DATABASENAME=lexgodb
DATABASEUSER=lexgoadmin
DATABASEPASSWORD=your-password
DATABASEHOST=your-rds-endpoint
DATABASEPORT=5432
DATABASE_URL=postgres://user:pass@host:5432/db?sslmode=require

# AWS
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_SESSION_TOKEN=your-token  # si aplica
AWS_STORAGE_BUCKET_NAME=your-bucket-name
AWS_S3_REGION_NAME=us-east-1

# OpenAI
OPENAI_API_KEY=your-openai-key
GPT_PROVIDER=openai
GPT_SUMMARIZER_MODEL=gpt-4o
GPT_VERIFIER_MODEL=gpt-4o-mini
GPT_GRAMMAR_MODEL=gpt-4o-mini

# Embeddings
OPENAI_EMBED_MODEL=text-embedding-3-small
EMBEDDINGS_DIM=1536

# Tavily (búsqueda web)
TAVILY_API_KEY=your-tavily-key
```

### Instalación Local
```bash
# Clonar repositorio
git clone https://github.com/tu-usuario/Tesis_Back.git
cd Tesis_Back

# Crear virtualenv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r requirements.txt

# Configurar .env
cp .env.example .env
# Editar .env con tus credenciales

# Migraciones
python manage.py migrate

# Crear superusuario
python manage.py createsuperuser

# Correr servidor de desarrollo
python manage.py runserver
```

### Deployment con Terraform
```bash
# Configurar variables
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Editar terraform.tfvars

# Inicializar Terraform
terraform init

# Planificar deployment
terraform plan

# Aplicar infraestructura
terraform apply

# Outputs importantes
terraform output backend_url
terraform output database_endpoint
terraform output s3_bucket_documentos
```

### Deployment Manual en EC2

Ver documentación completa en: [docs/deployment.md](docs/deployment.md)

Resumen:
1. Conectar via SSH
2. Instalar dependencias del sistema
3. Clonar repositorio
4. Configurar virtualenv y .env
5. Ejecutar migraciones
6. Configurar Gunicorn como servicio systemd
7. Verificar health check

## 📁 Estructura del Proyecto
```
Tesis_Back/
├── apps/
│   ├── conversations/      # Gestión de conversaciones con IA
│   ├── cases/             # Gestión de casos legales
│   ├── documents/         # Procesamiento de documentos
│   ├── jurisprudence/     # Búsqueda de jurisprudencia
│   ├── users/             # Autenticación y usuarios
│   └── tasks/             # Tareas y procedimientos
├── tesis_api/             # Configuración Django
├── terraform/             # Infrastructure as Code
├── requirements.txt       # Dependencias Python
└── manage.py
```

## 🔑 Features Principales

### 1. Gestión de Casos
- CRUD completo de expedientes
- Organización por etapas procesales
- Vinculación de documentos y tareas
- Trazabilidad de cambios

### 2. Procesamiento de Documentos
- Upload a S3 con encriptación
- OCR con AWS Textract
- Extracción automática de metadatos
- Generación de embeddings para búsqueda semántica

### 3. Asistente de Jurisprudencia
- Búsqueda vectorial con pgvector
- Análisis contextual con GPT-4
- Integración con búsqueda web (Tavily)
- Respuestas fundamentadas con citas

### 4. Machine Learning
- Clasificación automática de tipo de caso
- Detección de etapa procesal
- Sugerencias de estructura de expediente

### 5. Trazabilidad
- Auditoría completa de acciones
- Timestamps automáticos
- Historial de cambios en casos y documentos

## 🔒 Seguridad

- Autenticación JWT con djangorestframework-simplejwt
- CORS configurado para frontend específico
- Encriptación S3 (AES256)
- Conexiones PostgreSQL con SSL
- Security groups restrictivos en AWS
- Variables sensibles en .env (no commiteadas)

## 📝 Troubleshooting

### Problemas Comunes

**1. Error de conexión a PostgreSQL:**
```bash
# Verificar security groups en AWS
# Asegurar que el SG del EC2 puede acceder al SG del RDS puerto 5432
```

**2. Dependencias de Windows en Linux:**
```bash
# Eliminar pywin32 y pyreadline3 de requirements.txt
sed -i '/pywin32/d' requirements.txt
sed -i '/pyreadline3/d' requirements.txt
```

**3. Credenciales AWS expiradas (Student Lab):**
```bash
# Renovar credenciales en AWS Academy
# Actualizar .env con nuevas credenciales
# Reiniciar Gunicorn: sudo systemctl restart gunicorn
```

## 👥 Autores

**Micaela Suárez y Rafael Gini**
- Universidad Argentina de la Empresa (UADE)
- Carrera: Ingeniería en Informática
- Año: 2025


---

**Estado del Proyecto**: En Desarrollo - Tesis de Grado 2025
