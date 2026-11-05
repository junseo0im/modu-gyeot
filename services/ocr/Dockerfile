FROM python:3.12-slim-bookworm
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.py /app/server.py
USER 10001:10001
ENV OMP_THREAD_LIMIT=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-B", "/app/server.py"]