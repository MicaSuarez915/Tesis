# Gunicorn configuration
# El endpoint /crear-desde-documento/ puede tardar hasta ~150s
# (Textract async polling 120s max + OpenAI ~15s + DB ops)
timeout = 300        # 5 minutos
graceful_timeout = 30
keepalive = 5
workers = 2
worker_class = "sync"
