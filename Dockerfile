# Base image
FROM python:3.11-slim

# Environment config
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    wget \
    libglib2.0-0 \
    libnss3 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libdrm2 \
    libgbm1 \
    libxshmfence1 \
    libxss1 \
    libxtst6 \
    libpci3 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies
COPY requerimientos.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requerimientos.txt

# Install Playwright and browser binaries
RUN python -m playwright install --with-deps chromium

# Copy project files
COPY . .

# Run script
CMD ["python", "main.py"]
