# Imagen del agente: Python 3.11 + dependencias del proyecto.
# Se construye desde la RAÍZ del repositorio con:  docker compose up --build
# Copia el repositorio completo para que las rutas sean iguales que en el computador
# (el código en APP_AGENTE_CURACAVI/, el README y EVIDENCIAS_TEST/ al lado, que revisan las pruebas).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/modelos \
    TZ=America/Santiago

# Zona horaria de Chile: la fecha "de hoy" define los plazos hábiles que calcula el agente.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/APP_AGENTE_CURACAVI

# 1) PyTorch en versión CPU (MiniLM no necesita GPU y la imagen pesa ~2 GB menos).
# 2) El resto de las dependencias. Se instalan antes de copiar el código para aprovechar la caché de
#    Docker: si solo cambia el código, no se reinstala nada.
COPY APP_AGENTE_CURACAVI/requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

COPY . /repo

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

# Al arrancar: crea tablas e índices solo si faltan (la primera vez descarga MiniLM) y abre la interfaz.
CMD ["sh", "-c", "python -m scripts.preparar_datos --si-falta && streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true"]
