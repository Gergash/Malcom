FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Solo instalamos dependencias básicas de sistema para análisis de datos
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requerimientos.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Comando para arrancar el bot
CMD ["python", "app/main.py"]