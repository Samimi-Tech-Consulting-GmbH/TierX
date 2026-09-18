# Hybrid document retrieval

TierX retains MongoDB/GridFS as the source of truth. Optional Mem0 OSS adds a
self-hosted semantic index; it does not learn from analyst verdicts or LLM output.
Original text is embedded with `infer=false`. No extraction LLM is called.

```yaml
knowledge_base:
  enabled: true
  top_k: 5
  retrieval_mode: hybrid
```

Omitting `retrieval_mode` retains deterministic behavior. New revisions can select
the mode in the playbook upload form; the default preserves the uploaded YAML.

## Processing and retrieval

The existing processor builds deterministic chunks first. A separate leased
single-worker queue indexes source-preserving subchunks that fit the embedding
model. `semantic_index` reports PENDING, PROCESSING, INDEXED or FAILED separately
from the document's deterministic status. Reprocess creates a new generation.

Indexing has three bounded attempts. After a transient provider outage exhausts
them, restore the provider and use the existing administrator **Reprocess** control
(`POST /api/v1/tenants/{tenant_id}/knowledge-base/documents/{document_id}/reprocess`).
This builds a new deterministic generation and a fresh semantic job; failed jobs
do not retry forever. Failed staging vectors are removed, while previous successful
generations are retained until the replacement is indexed (or the file is deleted).
They cannot be returned if they no longer match MongoDB's active generation.

Job ownership is fenced on the document with an expiring lease token and monotonic
attempt number. Activation and failure updates require that same unexpired token.
A completed document is the commit record: recovery reconciles an unfinished job
acknowledgement before considering its vectors for cleanup. The ten-minute lease
allows the bounded embedding lock wait and HTTP calls; it renews between subchunks.

Mem0 stores tenant-scoped vectors in private Qdrant. Every search hit is checked
against MongoDB's current document generation, deletion flag and source checksum.
Selected text always comes from MongoDB, not Mem0's returned memory text.
Deletion excludes evidence immediately; durable cleanup removes derived vectors
when semantic indexing is running again. No conversational history is retained.

Exact security entities and CIDR containment take priority. Other matches use
equal-weight reciprocal rank fusion (constant 60). Semantic cosine similarity is
not added to deterministic points. The provisional minimum cosine similarity is
0.70. Responses report each channel, score, model digest and fallback status.

`POST /api/v1/tenants/{tenant_id}/knowledge-base/search` accepts `query`, `top_k`
and optional `retrieval_mode`. Existing tenant authorization applies. Test Search
lets users switch modes. Semantic failures preserve deterministic evidence and
report `degraded=true`. Query construction during enrichment uses only the existing
normalized field allowlist; raw alerts never reach the semantic service.

Cluster analysis retains document/version/chunk citations, contributing alert IDs,
model provenance, ten-chunk and 32-KiB limits. Text remains untrusted evidence, not
instructions, executable policy, or an automatic severity/verdict override.

## Local runtime

The default Compose includes private `kb-semantic` and `qdrant` services. Both flags
default false: `TIERX_KB_SEMANTIC_INDEXING_ENABLED` and
`TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED`. Enable indexing only after explicitly pulling
`granite-embedding:278m` into Ollama and verifying digest
`1a37926bf842899cbf90583e3932f3820548716d9d07661ba622199ffe95c552`.
The multilingual embedding model has a 512-token context; the pinned tokenizer
splits exact source text conservatively and Ollama receives `truncate=false`.

Only public build-time tokenizer/model artifacts are downloaded. Runtime telemetry
is disabled and local providers are explicit. Embedding calls serialize. Busy or
slow embedding returns deterministic fallback within the search budget.

Do not enable retrieval until fixture relevance, German/English paraphrases,
negative queries, tenant isolation and contention checks pass. Changes to the
model/digest require a new semantic index generation and renewed threshold checks.
Disabling both flags rolls back to deterministic retrieval without removing files.

Run `python evaluate.py --fixtures ../backend/tests/fixtures/knowledge_base
--tokenizer /models/tokenizer.json --ollama-url http://ollama:11434` from
`kb_semantic` against an explicitly configured local model to evaluate the golden
fixture queries. The command exits nonzero if any positive is below 0.70 or the
negative is accepted. It reports only case identifiers, document names and scores.
This real-model evaluation is separate from mocked CI tests and must pass before
enabling hybrid retrieval. A threshold change requires a broader negative test set,
recorded evaluation results and a deployment configuration change.

Mem0/Qdrant/tokenizer dependencies and the Granite model are Apache-2.0; the Ollama
Python client is MIT. The model is downloaded separately, not embedded in the
application image. Application code remains AGPL-3.0-only.
