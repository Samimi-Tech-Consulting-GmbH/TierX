FROM python:3.11-slim

WORKDIR /app
ARG APP_RELEASE_SHA=development
ARG APP_RELEASE_VERSION=development
ENV APP_RELEASE_SHA=${APP_RELEASE_SHA} APP_RELEASE_VERSION=${APP_RELEASE_VERSION}

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY kb_shared /kb_shared
COPY pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline .

CMD ["python", "main.py"]
