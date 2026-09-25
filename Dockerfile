# ==============================================================================
# Dockerfile - Live Subtitle & Translation Gateway
# Optimizado con python:3.11-slim, usuario no-root y healthcheck integrado
# ==============================================================================

FROM python:3.11-slim AS base

# Variables de entorno de Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instalar dependencias del sistema mínimas (incluyendo libportaudio2 por si se usa el worker)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Crear usuario sin privilegios para ejecución segura
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente, módulos, modelos y archivos estáticos
COPY backend/ ./backend/
COPY models/ ./models/
COPY scripts/ ./scripts/
COPY static/ ./static/

# Asegurar permisos correctos
RUN chown -R appuser:appgroup /app

USER appuser

# Exponer el puerto del Gateway WebSockets
EXPOSE 8000

# Healthcheck nativo consultando el endpoint de salud
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Comando por defecto para iniciar el servidor
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
