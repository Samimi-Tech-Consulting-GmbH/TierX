#!/usr/bin/env python3
"""Verify canonical TierX product and deployment identifiers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "README.md": ("TierX",),
    "backend/app/db/mongodb.py": ('db="tierx_platform"',),
    "backend/app/services/tenant_service.py": ('f"tierx_tenant_{safe_slug}"',),
    "frontend/src/lib/storage.ts": ('"tierx_token"', '"tierx_selected_tenant"'),
    "compose.yaml": ("container_name: tierx_backend", "container_name: tierx_mongodb"),
    "integrations/jira-forge/manifest.yml": ("tierx-send-issue", "tierx-configure", "tierx-jira-submit"),
}

def missing_identifiers(text, expected):
    return [value for value in expected if value not in text]

def main():
    failures = []
    for relative, expected in EXPECTED.items():
        missing = missing_identifiers((ROOT / relative).read_text(), expected)
        failures.extend(f"{relative}: missing canonical identifier {value}" for value in missing)
    if failures:
        raise SystemExit("\n".join(failures))

if __name__ == "__main__":
    main()
