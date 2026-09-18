from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from importlib.resources import files
from typing import Any, Iterable
from urllib.parse import urlparse

from markdown_it import MarkdownIt

PARSER_VERSION = "commonmark-v1"
INDEX_VERSION = "lexical-v1"
RETRIEVAL_VERSION = "kb-retrieval-v1"
TARGET_CHARS = 2_400
MAX_CHARS = 3_200
WINDOW_CHARS = 3_000
WINDOW_OVERLAP = 300
MIN_SCORE = 20.0

TOKEN_RE = re.compile(r"[\w@./:\\-]+", re.UNICODE)
URL_RE = re.compile(r"https?://[^\s<>\])}]+", re.IGNORECASE)
DOMAIN_RE = re.compile(
    r"(?<![@\w.-])(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,62})\.)+" r"[a-zA-Z]{2,63}(?![\w-])"
)
CIDR_RE = re.compile(r"(?<![\w:])(?:[0-9a-fA-F:.]+)/\d{1,3}(?![\w:])")
IP_RE = re.compile(
    r"(?<![\w:])(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F]*:[0-9a-fA-F:]+)(?![\w:])"
)
HASH_RE = re.compile(
    r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![0-9a-fA-F])"
)
MITRE_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)
PORT_RE = re.compile(r"\b(?:port|tcp|udp)\s*[:=/ -]?\s*(\d{1,5})\b", re.IGNORECASE)

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "aber",
    "als",
    "am",
    "an",
    "auf",
    "aus",
    "bei",
    "das",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "ein",
    "eine",
    "einer",
    "für",
    "im",
    "in",
    "ist",
    "mit",
    "oder",
    "sich",
    "und",
    "von",
    "zu",
    "zum",
    "zur",
}

# Audited, deliberately small vocabulary. Any content change requires a new
# dictionary file and a retrieval-version bump.
_SYNONYM_RESOURCE = files("tierx_kb").joinpath("synonyms-v1.json")
_SYNONYM_DATA = json.loads(_SYNONYM_RESOURCE.read_text(encoding="utf-8"))
if _SYNONYM_DATA.get("version") != "soc-synonyms-v1":
    raise RuntimeError("Unexpected Knowledge Base synonym dictionary version")
SYNONYM_GROUPS = tuple(set(group) for group in _SYNONYM_DATA["groups"])

SYNONYMS: dict[str, set[str]] = {}
for group in SYNONYM_GROUPS:
    normalized = {unicodedata.normalize("NFKC", value).casefold() for value in group}
    for term in normalized:
        SYNONYMS[term] = normalized - {term}

ALERT_FIELDS = (
    "event.category",
    "event.action",
    "event.outcome",
    "rule.name",
    "host.name",
    "host.hostname",
    "host.ip",
    "host.domain",
    "source.ip",
    "source.domain",
    "source.port",
    "destination.ip",
    "destination.domain",
    "destination.port",
    "client.ip",
    "client.domain",
    "client.port",
    "server.ip",
    "server.domain",
    "server.port",
    "user.name",
    "process.name",
    "process.command_line",
    "file.name",
    "file.path",
    "file.hash.md5",
    "file.hash.sha1",
    "file.hash.sha256",
    "url.full",
    "url.domain",
    "network.protocol",
    "threat.technique.id",
    "threat.technique.name",
    "mitre.technique.id",
)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("_", " ")
    value = re.sub(r"[^\w@./:\\-]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def tokenize(value: str) -> list[str]:
    tokens = []
    for raw_token in TOKEN_RE.findall(normalize_text(value)):
        token = raw_token.strip("./:\\-")
        candidates = [token]
        # Keep path/indicator-shaped tokens intact while also making ordinary
        # hyphenated prose (for example "PowerShell-Befehle") searchable by
        # its component terms.
        candidates.extend(part for part in re.split(r"[-–—]", token) if part != token)
        for candidate in candidates:
            if len(candidate) < 2 or candidate in STOP_WORDS:
                continue
            tokens.append(candidate)
    return tokens


def _scalar_values(value: Any) -> Iterable[str]:
    if isinstance(value, (str, int, float, bool)):
        text = str(value).strip()
        if text:
            yield text
    elif isinstance(value, list):
        for item in value:
            yield from _scalar_values(item)


def _resolve(payload: dict[str, Any], path: str) -> Any:
    if path in payload:
        return payload[path]
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip("[]")))
    except ValueError:
        return None


def extract_indicators(text: str) -> dict[str, list[str]]:
    cidrs: set[str] = set()
    for candidate in CIDR_RE.findall(text):
        try:
            cidrs.add(str(ipaddress.ip_network(candidate, strict=False)))
        except ValueError:
            pass
    ips: set[str] = set()
    for candidate in IP_RE.findall(text):
        valid = _valid_ip(candidate)
        if valid:
            ips.add(valid)
    urls = {value.rstrip(".,;") for value in URL_RE.findall(text)}
    domains = {value.casefold() for value in DOMAIN_RE.findall(text)}
    for url in urls:
        hostname = urlparse(url).hostname
        if hostname and not _valid_ip(hostname):
            domains.add(hostname.casefold())
    hashes = {value.casefold() for value in HASH_RE.findall(text)}
    techniques = {value.upper() for value in MITRE_RE.findall(text)}
    ports = {
        str(int(value)) for value in PORT_RE.findall(text) if 0 < int(value) <= 65535
    }
    return {
        "ips": sorted(ips),
        "cidrs": sorted(cidrs),
        "urls": sorted(urls),
        "domains": sorted(domains),
        "hashes": sorted(hashes),
        "mitre_techniques": sorted(techniques),
        "ports": sorted(ports, key=int),
    }


@dataclass
class _Block:
    text: str
    start_line: int
    end_line: int
    headings: list[str]


def _markdown_blocks(text: str) -> list[_Block]:
    lines = text.splitlines()
    tokens = MarkdownIt("commonmark").parse(text)
    headings: list[str] = []
    blocks: list[_Block] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open" and token.map and index + 1 < len(tokens):
            level = int(token.tag[1:])
            title = tokens[index + 1].content.strip()
            headings = headings[: level - 1] + [title]
            index += 1
        elif token.map and token.type in {
            "paragraph_open",
            "bullet_list_open",
            "ordered_list_open",
            "fence",
            "code_block",
            "blockquote_open",
            "table_open",
        }:
            start, end = token.map
            raw = "\n".join(lines[start:end]).strip()
            if raw and not any(
                existing.start_line == start + 1 and existing.end_line == end
                for existing in blocks
            ):
                blocks.append(_Block(raw, start + 1, end, list(headings)))
        index += 1
    if not blocks and text.strip():
        return _text_blocks(text)
    blocks.sort(key=lambda block: (block.start_line, block.end_line))
    # Remove nested blocks already covered by a parent list/quote block.
    compact: list[_Block] = []
    for block in blocks:
        if (
            compact
            and block.start_line >= compact[-1].start_line
            and block.end_line <= compact[-1].end_line
        ):
            continue
        compact.append(block)
    return compact


def _text_blocks(text: str) -> list[_Block]:
    lines = text.splitlines()
    blocks: list[_Block] = []
    start: int | None = None
    for index, line in enumerate([*lines, ""], start=1):
        if line.strip() and start is None:
            start = index
        if not line.strip() and start is not None:
            raw = "\n".join(lines[start - 1 : index - 1]).strip()
            blocks.append(_Block(raw, start, index - 1, []))
            start = None
    return blocks


def _split_long(block: _Block) -> list[_Block]:
    if len(block.text) <= MAX_CHARS:
        return [block]
    result: list[_Block] = []
    start = 0
    while start < len(block.text):
        end = min(len(block.text), start + WINDOW_CHARS)
        if end < len(block.text):
            whitespace = block.text.rfind(" ", start + WINDOW_CHARS // 2, end)
            if whitespace > start:
                end = whitespace
        piece = block.text[start:end].strip()
        if piece:
            result.append(
                _Block(piece, block.start_line, block.end_line, block.headings)
            )
        if end >= len(block.text):
            break
        start = max(start + 1, end - WINDOW_OVERLAP)
    return result


def parse_document(
    text: str,
    *,
    file_format: str,
    document_id: str,
    document_version: int,
    document_sha256: str,
    index_generation: str,
) -> list[dict[str, Any]]:
    if file_format not in {"md", "txt"}:
        raise ValueError("Only Markdown and text documents can be processed")
    normalized_source = text.replace("\r\n", "\n").replace("\r", "\n")
    source_blocks = (
        _markdown_blocks(normalized_source)
        if file_format == "md"
        else _text_blocks(normalized_source)
    )
    blocks = [part for block in source_blocks for part in _split_long(block)]
    packed: list[_Block] = []
    for block in blocks:
        if (
            packed
            and packed[-1].headings == block.headings
            and len(packed[-1].text) + 2 + len(block.text) <= MAX_CHARS
            and len(packed[-1].text) < TARGET_CHARS
        ):
            previous = packed[-1]
            packed[-1] = _Block(
                previous.text + "\n\n" + block.text,
                previous.start_line,
                block.end_line,
                previous.headings,
            )
        else:
            packed.append(block)

    chunks: list[dict[str, Any]] = []
    for chunk_index, block in enumerate(packed):
        checksum = hashlib.sha256(block.text.encode("utf-8")).hexdigest()
        identity = ":".join(
            [
                document_sha256,
                str(document_version),
                PARSER_VERSION,
                str(block.start_line),
                str(block.end_line),
                checksum,
            ]
        )
        terms = tokenize(" ".join([*block.headings, block.text]))
        chunks.append(
            {
                "chunk_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                "document_id": document_id,
                "document_version": document_version,
                "index_generation": index_generation,
                "chunk_index": chunk_index,
                "source_start_line": block.start_line,
                "source_end_line": block.end_line,
                "heading_path": block.headings,
                "text": block.text,
                "text_sha256": checksum,
                "normalized_text": normalize_text(
                    " ".join([*block.headings, block.text])
                ),
                "normalized_terms": sorted(set(terms)),
                "term_frequencies": dict(sorted(Counter(terms).items())),
                "term_count": len(terms),
                "indicators": extract_indicators(block.text),
                "parser_version": PARSER_VERSION,
                "index_version": INDEX_VERSION,
            }
        )
    return chunks


def _query(values: list[tuple[str, str]]) -> dict[str, Any]:
    phrases = []
    field_values = []
    ips = []
    for field, value in values:
        normalized = normalize_text(value)
        if not normalized:
            continue
        phrases.append(normalized)
        field_values.append({"field": field, "value": value, "normalized": normalized})
        valid_ip = _valid_ip(value)
        if valid_ip:
            ips.append(valid_ip)
    terms = tokenize(" ".join(phrases))
    expanded = set(terms)
    synonym_hits: dict[str, list[str]] = {}
    for term in terms:
        related = SYNONYMS.get(term, set())
        if related:
            synonym_hits[term] = sorted(related)
            expanded.update(related)
    return {
        "phrases": sorted(set(phrases)),
        "field_values": field_values,
        "terms": sorted(set(terms)),
        "expanded_terms": sorted(expanded),
        "synonyms": synonym_hits,
        "ips": sorted(set(ips)),
    }


def build_text_query(text: str) -> dict[str, Any]:
    return _query([("query", text[:4096])])


def build_alert_query(alert_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    values = [("alert_type", alert_type)]
    for field in ALERT_FIELDS:
        for value in _scalar_values(_resolve(payload, field)):
            values.append((field, value[:1024]))
    return _query(values)


def mongo_candidate_filter(query: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded-retrieval prefilter that is safe for MongoDB 4.4.

    It deliberately performs no scoring. Every active generation remains in
    scope; this filter only avoids loading chunks that cannot have an exact,
    synonym, lexical, or CIDR reason. Fuzzy scoring is therefore limited to a
    candidate already selected by one of those deterministic reasons.
    """
    reasons: list[dict[str, Any]] = []
    terms = sorted(set(query.get("expanded_terms") or []))
    if terms:
        reasons.append({"normalized_terms": {"$in": terms}})
    if query.get("ips"):
        reasons.extend(
            [
                {"indicators.ips": {"$in": query["ips"]}},
                {"indicators.cidrs.0": {"$exists": True}},
            ]
        )
    return {"$or": reasons} if reasons else {"_id": {"$exists": False}}


def _cidr_matches(chunk: dict[str, Any], query: dict[str, Any]) -> list[dict[str, str]]:
    matches = []
    for raw_cidr in chunk.get("indicators", {}).get("cidrs", []):
        try:
            network = ipaddress.ip_network(raw_cidr, strict=False)
        except ValueError:
            continue
        for raw_ip in query.get("ips", []):
            try:
                address = ipaddress.ip_address(raw_ip)
            except ValueError:
                continue
            if address.version == network.version and address in network:
                matches.append(
                    {
                        "method": "CIDR_CONTAINS",
                        "value": raw_ip,
                        "selector": str(network),
                    }
                )
    return matches


def rank_chunks(
    chunks: list[dict[str, Any]], query: dict[str, Any], *, top_k: int = 5
) -> list[dict[str, Any]]:
    top_k = max(1, min(20, int(top_k)))
    query_terms = set(query.get("terms") or [])
    expanded_terms = set(query.get("expanded_terms") or [])
    if not query_terms and not query.get("ips"):
        return []
    document_frequency = Counter()
    for chunk in chunks:
        document_frequency.update(set(chunk.get("normalized_terms") or []))
    average_length = (
        sum(max(1, int(chunk.get("term_count") or 0)) for chunk in chunks) / len(chunks)
        if chunks
        else 1.0
    )
    maximum_bm25 = 0.0
    scored: list[tuple[dict[str, Any], float, list[dict[str, Any]], float, float]] = []
    for chunk in chunks:
        terms = set(chunk.get("normalized_terms") or [])
        frequencies = chunk.get("term_frequencies") or {}
        normalized = str(chunk.get("normalized_text") or "")
        reasons: list[dict[str, Any]] = []
        base = 0.0
        cidr = _cidr_matches(chunk, query)
        if cidr:
            base += 120.0 * len(cidr)
            reasons.extend(cidr)
        exact_values = []
        indicators = chunk.get("indicators", {})
        for entry in query.get("field_values") or []:
            value = entry["normalized"]
            field = str(entry.get("field") or "")
            if field == "query":
                continue
            if field.endswith(".ip"):
                matched = (_valid_ip(entry["value"]) or "") in indicators.get("ips", [])
            elif field.endswith(".port"):
                matched = str(entry["value"]) in indicators.get("ports", [])
            elif ".hash." in field:
                matched = value in indicators.get("hashes", [])
            elif "technique" in field:
                matched = str(entry["value"]).upper() in indicators.get(
                    "mitre_techniques", []
                )
            else:
                matched = bool(
                    value
                    and (
                        value in terms
                        or re.search(rf"(?<!\w){re.escape(value)}(?!\w)", normalized)
                    )
                )
            if matched:
                exact_values.append(entry)
        if exact_values:
            base += 100.0 * len(exact_values)
            reasons.extend(
                {
                    "method": "EXACT_ENTITY",
                    "field": item["field"],
                    "value": item["value"],
                }
                for item in exact_values
            )
        phrase_matches = [
            phrase
            for phrase in query.get("phrases") or []
            if " " in phrase and phrase in normalized
        ]
        if phrase_matches:
            base += 40.0
            reasons.append({"method": "EXACT_PHRASE", "values": phrase_matches[:5]})
        synonym_terms = sorted((expanded_terms - query_terms) & terms)
        if synonym_terms:
            points = min(60.0, 20.0 * len(synonym_terms))
            base += points
            reasons.append({"method": "SOC_SYNONYM", "values": synonym_terms[:10]})

        bm25 = 0.0
        length = max(1, int(chunk.get("term_count") or 0))
        for term in expanded_terms & terms:
            frequency = max(1, int(frequencies.get(term, 1)))
            docs = max(1, int(document_frequency[term]))
            inverse = math.log(1 + (len(chunks) - docs + 0.5) / (docs + 0.5))
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * length / average_length)
            bm25 += inverse * (frequency * 2.2 / denominator)
        maximum_bm25 = max(maximum_bm25, bm25)

        fuzzy = 0.0
        if base > 0 or bm25 > 0:
            for query_term in query_terms:
                for term in terms:
                    ratio = SequenceMatcher(None, query_term, term).ratio()
                    if ratio >= 0.85 and query_term != term:
                        fuzzy = max(fuzzy, ratio)
            if fuzzy:
                reasons.append({"method": "FUZZY_TERM", "ratio": round(fuzzy, 4)})
        scored.append((chunk, base, reasons, bm25, fuzzy))

    results = []
    for chunk, base, reasons, bm25, fuzzy in scored:
        score = base
        if maximum_bm25 > 0 and bm25 > 0:
            lexical_points = 30.0 * bm25 / maximum_bm25
            score += lexical_points
            reasons.append(
                {
                    "method": "BM25",
                    "score": round(bm25, 6),
                    "points": round(lexical_points, 4),
                }
            )
        if fuzzy >= 0.85:
            score += 15.0 * fuzzy
        if score < MIN_SCORE:
            continue
        results.append({**chunk, "score": round(score, 4), "matched_by": reasons})
    results.sort(
        key=lambda item: (
            -item["score"],
            str(item.get("document_id") or ""),
            int(item.get("document_version") or 0),
            int(item.get("chunk_index") or 0),
        )
    )
    return results[:top_k]
