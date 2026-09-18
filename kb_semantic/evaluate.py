"""Opt-in, real-model fixture evaluation. Prints IDs/scores only, no source text."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from tokenizers import Tokenizer
from tierx_kb import parse_document

from engine import LocalEmbedder, MODEL_DIGEST, subchunks


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right)) / (
        math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--ollama-url", default="http://ollama:11434")
    args = parser.parse_args()
    tokenizer = Tokenizer.from_file(args.tokenizer)
    tokenizer.no_truncation()
    embedder = LocalEmbedder(args.ollama_url, tokenizer)
    corpus = []
    for path in sorted(Path(args.fixtures).glob("*")):
        if path.suffix not in {".md", ".txt"}:
            continue
        text = path.read_text()
        chunks = parse_document(
            text,
            file_format=path.suffix[1:],
            document_id=path.name,
            document_version=1,
            document_sha256=hashlib.sha256(text.encode()).hexdigest(),
            index_generation="evaluation",
        )
        for chunk in chunks:
            for start, end, part in subchunks(chunk["text"], tokenizer):
                corpus.append(
                    (path.name, chunk["chunk_id"], start, end, embedder.embed(part))
                )
    cases = [
        (
            "german-auth",
            "Interaktive Anmeldung eines Dienstkontos über Remotedesktop",
            "02_identity.md",
        ),
        (
            "english-auth",
            "A non-human backup account was used for an interactive remote desktop session",
            "02_identity.md",
        ),
        (
            "scanner",
            "Which machine is authorized to probe network ports?",
            "01_network.md",
        ),
        ("negative", "Banana orchard harvest and tropical fruit recipes", None),
    ]
    results = []
    for case, query, expected in cases:
        vector = embedder.embed(query, "search")
        ranked = sorted(
            ((cosine(vector, item[-1]), item[0], item[1]) for item in corpus),
            reverse=True,
        )
        accepted = [item for item in ranked if item[0] >= 0.70]
        results.append(
            {
                "case": case,
                "expected_document": expected,
                "top_document": ranked[0][1],
                "top_cosine": round(ranked[0][0], 4),
                "accepted_documents": sorted({item[1] for item in accepted}),
                "passes_at_070": (expected in {item[1] for item in accepted})
                if expected
                else not accepted,
            }
        )
    print(json.dumps({"model_digest": MODEL_DIGEST, "results": results}, indent=2))
    if not all(row["passes_at_070"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
