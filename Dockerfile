FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r api/requirements.txt

COPY . .

ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8002

EXPOSE 8002

CMD ["sh", "-c", "cd /app/api && uvicorn server:app --host ${BACKEND_HOST:-0.0.0.0} --port ${BACKEND_PORT:-8002}"]
