"""Local-only Mem0 adapter. No conversational memory or fact inference."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import logging

os.environ["MEM0_TELEMETRY"] = "false"
logging.getLogger("mem0").setLevel(logging.CRITICAL)

import httpx
from tokenizers import Tokenizer

MODEL = "granite-embedding:278m"
MODEL_DIGEST = "1a37926bf842899cbf90583e3932f3820548716d9d07661ba622199ffe95c552"
TOKENIZER_REVISION = "a9cb5338491faf32b73dd17b714a31821c021bbf"  # gitleaks:allow public Hugging Face commit, not a credential
INDEX_VERSION = "kb-semantic-v1"
MODEL_ID = hashlib.sha256(
    f"{INDEX_VERSION}:{MODEL_DIGEST}:{TOKENIZER_REVISION}".encode()
).hexdigest()


def checksum(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def subchunks(text, tokenizer, maximum=480):
    """Exact, contiguous source slices; leave room for model special tokens."""
    start = 0
    while start < len(text):
        lo, hi = start + 1, len(text)
        end = start
        while lo <= hi:
            middle = (lo + hi) // 2
            if len(tokenizer.encode(text[start:middle]).ids) <= maximum:
                end, lo = middle, middle + 1
            else:
                hi = middle - 1
        if end == start:
            raise ValueError("TOKEN_LIMIT")
        yield start, end, text[start:end]
        start = end


class LocalEmbedder:
    def __init__(self, url, tokenizer):
        self.url = url.rstrip("/")
        self.tokenizer = tokenizer
        self.lock = threading.Lock()

    def embed(self, text, memory_action=None):
        if len(self.tokenizer.encode(text).ids) > 500:
            raise ValueError("TOKEN_LIMIT")
        timeout = 3.5 if memory_action == "search" else 120
        if not self.lock.acquire(timeout=0.05 if memory_action == "search" else 120):
            raise TimeoutError("EMBEDDER_BUSY")
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                tags = client.get(self.url + "/api/tags")
                tags.raise_for_status()
                if not any(
                    m.get("name") == MODEL
                    and m.get("digest", "").removeprefix("sha256:") == MODEL_DIGEST
                    for m in tags.json().get("models", [])
                ):
                    raise ValueError("MODEL_DIGEST_MISMATCH")
                response = client.post(
                    self.url + "/api/embed",
                    json={
                        "model": MODEL,
                        "input": text,
                        "truncate": False,
                        "keep_alive": "5m",
                    },
                )
                response.raise_for_status()
                vector = response.json()["embeddings"][0]
                if len(vector) != 768:
                    raise ValueError("EMBEDDING_DIMENSIONS")
                return vector
        finally:
            self.lock.release()


class Mem0LocalEmbedder(LocalEmbedder):
    def __init__(self, config):
        tokenizer = Tokenizer.from_file(
            os.getenv("KB_TOKENIZER_PATH", "/models/tokenizer.json")
        )
        tokenizer.no_truncation()
        super().__init__(config.ollama_base_url, tokenizer)


class Engine:
    def __init__(self):
        from mem0 import Memory
        from mem0.utils.factory import EmbedderFactory
        from qdrant_client import QdrantClient

        # Replace Ollama's auto-pulling adapter with our fail-closed, no-truncation adapter.
        EmbedderFactory.provider_to_class["ollama"] = "engine.Mem0LocalEmbedder"
        self.tokenizer = Tokenizer.from_file(
            os.getenv("KB_TOKENIZER_PATH", "/models/tokenizer.json")
        )
        self.tokenizer.no_truncation()
        url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.memory = Memory.from_config(
            {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "host": os.getenv("QDRANT_HOST", "qdrant"),
                        "port": 6333,
                        "client": QdrantClient(
                            host=os.getenv("QDRANT_HOST", "qdrant"),
                            port=6333,
                            timeout=3,
                        ),
                        "collection_name": "tierx_kb_v1_768",
                        "embedding_model_dims": 768,
                    },
                },
                "embedder": {
                    "provider": "ollama",
                    "config": {"model": MODEL, "ollama_base_url": url},
                },
                "llm": {
                    "provider": "ollama",
                    "config": {"model": MODEL, "ollama_base_url": url},
                },
                "history_db_path": os.getenv("MEM0_HISTORY_PATH", "/data/history.db"),
            }
        )
        # Documents already have immutable source/provenance in MongoDB. Do not retain
        # an additional full-text copy in Mem0's conversational audit history.
        self.memory.db = NoConversationHistory()

    def ensure(self, tenant_id, text, metadata):
        # A crash after vector write but before Mongo acknowledgement is reconciled here.
        existing = self.memory.get_all(
            user_id=tenant_id,
            filters={"source_key": metadata["source_key"]},
            limit=1000,
        )["results"]
        if existing:
            ordered = sorted(existing, key=lambda m: m["id"])
            for duplicate in ordered[1:]:
                self.memory.delete(duplicate["id"])
            return ordered[0]["id"]
        result = self.memory.add(
            text, user_id=tenant_id, metadata=metadata, infer=False
        )
        return result["results"][0]["id"]

    def search(self, tenant_id, text):
        if len(self.tokenizer.encode(text).ids) > 500:
            raise ValueError("QUERY_TOO_LARGE")
        return self.memory.search(
            text,
            user_id=tenant_id,
            filters={"model_id": MODEL_ID},
            limit=50,
            rerank=False,
        )["results"]

    def delete_generation(self, tenant_id, generation):
        while True:
            rows = self.memory.get_all(
                user_id=tenant_id,
                filters={"semantic_generation": generation},
                limit=1000,
            )["results"]
            if not rows:
                break
            for row in rows:
                self.memory.delete(row["id"])


class NoConversationHistory:
    def add_history(self, *args, **kwargs):
        pass

    def get_history(self, *args, **kwargs):
        return []
