# Single Dockerfile that runs either the web service or the worker
# depending on the start command Render passes.

FROM python:3.12-slim

# poppler-utils — needed by pdf2image for vision-OCR fallback
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

# Default: run the web service. Override with `python worker.py` for the worker.
CMD ["sh", "-c", "gunicorn main:app -k uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT} --timeout 30 --keep-alive 5"]
