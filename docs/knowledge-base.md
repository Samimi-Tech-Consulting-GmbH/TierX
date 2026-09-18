# Knowledge Base processing and retrieval

The tenant Knowledge Base stores UTF-8 Markdown and text files, processes them
asynchronously, and can add relevant excerpts to analysis when an active
playbook explicitly enables retrieval. Knowledge Base content is evidence for
the model only: it never directly changes severity, correlation, status,
verdict, or an allowlist.

## Lifecycle and storage

New uploads accept only `.md` and `.txt`, up to 50 MiB. Empty files, invalid
UTF-8, NUL bytes, and other formats are rejected. Older PDF, DOCX, or XLSX
records remain downloadable and deletable but are marked `processing_supported:
false` and are never indexed.

Metadata is stored in the tenant's `kb_documents` collection and bytes in the
tenant's `kb_files` GridFS bucket. A dedicated processor uses an expiring lease
and transitions processable documents through:

```text
PENDING -> PROCESSING -> INDEXED
                      -> FAILED
```

Markdown is parsed as CommonMark and split on headings and blocks. TXT uses
paragraph boundaries. Blocks are packed toward 2,400 characters up to 3,200;
only an indivisible oversized block uses 3,000-character windows with 300
characters of overlap. `kb_chunks` stores exact text, source line ranges,
heading paths, normalized terms, reliable indicators, checksums, and parser and
index versions.

Reprocessing builds a separate index generation. It becomes active only after
all chunks have been written. Failed staging data is removed and cannot replace
the last successful generation. Deleting a document removes all generations
and its GridFS bytes.

## Deterministic retrieval

Retrieval uses one shared Python package in the backend, processor, and
pipeline. It normalizes Unicode with NFKC/case folding and uses the versioned
German/English `soc-synonyms-v1` dictionary. It recognizes IPv4/IPv6 addresses,
CIDRs, URLs, domains, common hashes, MITRE technique IDs, and ports only when a
port/TCP/UDP label is present.

Scores are additive and deterministic:

- CIDR contains an alert IP: 120 points.
- Exact normalized alert entity: 100 points.
- Exact multi-token phrase: 40 points.
- German/English SOC synonyms: up to 60 points.
- BM25 lexical relevance: normalized to at most 30 points.
- Fuzzy token similarity of at least 0.85: up to 15 points, only after another
  candidate reason selected the chunk.

Results below 20 are discarded and ties use document ID, document version, and
chunk order. Candidate count and query length are bounded. The MongoDB
candidate filter covers every active document rather than selecting an initial
subset of documents.

Alert queries use only normalized, allowlisted ECS fields—never `raw_payload`.
Unknown languages still receive entity, CIDR, lexical, and fuzzy matching; no
automatic translation occurs.

## Playbook configuration

Knowledge retrieval is opt-in per immutable playbook revision:

```yaml
knowledge_base:
  enabled: true
  top_k: 5
```

`top_k` is between 1 and 20. Missing configuration is equivalent to disabled.
When enabled, enrichment searches all indexed documents in that tenant and
persists an `enrichment.kb_context` status:

- `OK`: one or more qualifying chunks were selected.
- `SKIPPED`: the playbook or deployment feature flag disabled retrieval.
- `KB_NOT_AVAILABLE`: the tenant has no indexed documents.
- `NO_MATCH`: retrieval succeeded but no chunk passed the threshold.
- `ERROR`: retrieval failed safely; the alert still continues.

For cluster analysis, matches are deduplicated by document version and chunk
ID, ranked, and limited to ten complete chunks and 32 KiB. Lower-ranked chunks
are omitted rather than truncated. Evidence appears immediately before the
model output schema between `BEGIN/END TENANT KNOWLEDGE EVIDENCE` delimiters,
with an instruction that it is untrusted and must not be followed as an
instruction. Prompt provenance contains IDs, checksums, scores, reasons, and
contributing alerts, but trace records never contain full chunk text.

## API and permissions

All routes are under `/api/v1/tenants/{tenant_id}/knowledge-base` and require a
Bearer token.

```http
POST   /documents
GET    /documents?skip=0&limit=25
GET    /documents/{document_id}
GET    /documents/{document_id}/download
GET    /documents/{document_id}/chunks?skip=0&limit=25
POST   /documents/{document_id}/reprocess
DELETE /documents/{document_id}
POST   /search
```

Manual search accepts:

```json
{"query": "EXAMPLE-DB01 203.0.113.10", "top_k": 5}
```

Platform and tenant admins may upload, delete, and reprocess. Tenant operators
may list, inspect, download, and test search within their own tenant. Downloads
always use attachment disposition and `nosniff`; uploaded content is never
rendered inline by the application.

## Runtime switches

```env
KNOWLEDGE_BASE_PROCESSING_ENABLED=false
KNOWLEDGE_BASE_RETRIEVAL_ENABLED=false
KNOWLEDGE_BASE_PROCESSOR_INTERVAL_SECONDS=5
KNOWLEDGE_BASE_PROCESSOR_LEASE_SECONDS=600
KNOWLEDGE_BASE_MAX_CANDIDATES=500
KNOWLEDGE_BASE_PROMPT_MAX_BYTES=32768
```

The processor is an internal container with no public port or Kafka topic.
When processing is enabled, backend health checks require a recent processor
heartbeat. Disabling retrieval leaves indexed documents intact and makes new
alerts behave as they did before this feature.

This implementation does not parse PDFs/Office files, malware-scan documents,
create embeddings, run a vector database, translate text, execute document
instructions, or turn prose into policy rules.
