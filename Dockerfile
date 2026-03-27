FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    qpdf \
    libqpdf-dev \
    build-essential \
    pkg-config \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD gunicorn main:app --bind 0.0.0.0:${PORT:-8080}
