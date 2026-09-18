FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
WORKDIR /app
COPY kb_shared /kb_shared
COPY kb_semantic/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Download public tokenizer at image build time, never tenant data at runtime.
RUN mkdir /models && python -c "import urllib.request; urllib.request.urlretrieve('https://huggingface.co/ibm-granite/granite-embedding-278m-multilingual/resolve/a9cb5338491faf32b73dd17b714a31821c021bbf/tokenizer.json', '/models/tokenizer.json')"
COPY kb_semantic .
ENV MEM0_TELEMETRY=false HF_HUB_OFFLINE=1 MEM0_DIR=/data/mem0
RUN mkdir /data && useradd --uid 10001 --no-create-home tierx && chown -R tierx /data
USER tierx
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]
