#!/usr/bin/env python3
"""Reject active legacy branding outside permanent compatibility identifiers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = re.compile(r"soc[- _]?mind", re.IGNORECASE)
ALLOWED = [
    re.compile(pattern)
    for pattern in (
        r"\bSOC-Mind-main\b",
        r"ghcr\.io/(?:\$\{\{ github\.repository_owner \}\}|\$\{REGISTRY_NAMESPACE\})/soc-mind[-\w${}.:]*",
        r"/opt/soc-mind", r"\bsocmind_(?:backend|frontend|ingestion_proxy|init|kafka|kb_processor|mongodb|ollama|pipeline)\b",
        r"\bsoc_mind_(?:platform|tenant[_\w]*)\b", r"\bSOC_MIND_(?:[A-Z0-9_]+|\{_?name\}|\*)?",
        r"X-SOC-Mind-(?:[A-Za-z0-9{}-]+|\*)", r"x-soc-mind-[a-z{}-]+", r"\bsoc_mind_(?:token|onboarding_seen|selected_tenant)\b",
        r"\bsoc_mind_kb\b", r"\bsoc-mind:(?:config|integration-secret|submit|submission|pending|poll|webhook|enrichment-action)",
        r"\bSOC_MIND_ANALYSIS_DEFAULT\b", r"\bsoc_mind_(?:kpi|dashboard)_test_[A-Fa-f0-9{}_.]+",
        r"\bsoc-mind-(?:send-issue|configure|jira-submit)\b", r'"soc-mind"',
        r"\bsoc-mind-correlation-repair\b",
    )
]
IGNORED = {"LICENSE", "THIRD_PARTY_NOTICES.md", "sbom.cdx.json", "tools/check_branding.py", "tools/test_branding.py"}


def has_legacy_branding(line: str) -> bool:
    for allowed in ALLOWED:
        line = allowed.sub("", line)
    return bool(LEGACY.search(line))


def main() -> None:
    paths = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    failures = []
    for relative in paths:
        if relative in IGNORED or relative.startswith("docs/deployments/"):
            continue
        path = ROOT / relative
        try:
            lines = path.read_text(errors="strict").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if has_legacy_branding(line):
                failures.append(f"{relative}:{number}:{line.strip()}")
    if failures:
        raise SystemExit("Active legacy branding found:\n" + "\n".join(failures))


if __name__ == "__main__":
    main()
