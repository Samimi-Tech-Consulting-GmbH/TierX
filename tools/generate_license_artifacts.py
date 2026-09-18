#!/usr/bin/env python3
"""Generate deterministic CycloneDX inventory and third-party notices."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
LOCKS = (ROOT / "frontend/package-lock.json", ROOT / "integrations/jira-forge/package-lock.json")
REQUIREMENTS = (ROOT / "backend/requirements.txt", ROOT / "ingestion-proxy/requirements.txt", ROOT / "pipeline/requirements.txt", ROOT / "kb_semantic/requirements.txt")
PYPROJECTS = (ROOT / "kb_shared/pyproject.toml",)
NPM_LICENSE_EVIDENCE = json.loads((ROOT / "tools/npm_license_evidence.json").read_text())
PYTHON_LICENSE_EVIDENCE = json.loads((ROOT / "tools/python_license_evidence.json").read_text())


def license_declaration(value: str) -> dict:
    if value.startswith("SEE LICENSE"):
        return {"license": {"name": value}}
    if " OR " in value or " AND " in value or value.startswith("("):
        return {"expression": value}
    return {"license": {"id": value}}


def license_text(declaration: dict) -> str:
    if declaration.get("expression"):
        return declaration["expression"]
    license_value = declaration["license"]
    return license_value.get("id") or license_value["name"]


def npm_components(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    result = []
    for package_path, meta in data.get("packages", {}).items():
        if not package_path.startswith("node_modules/") or not meta.get("version"):
            continue
        name = package_path.rsplit("node_modules/", 1)[-1]
        item = {
            "type": "library", "name": name, "version": str(meta["version"]),
            "purl": f"pkg:npm/{quote(name, safe='/')}@{quote(str(meta['version']), safe='')}",
            "properties": [{"name": "tierx:manifest", "value": str(path.relative_to(ROOT))}],
        }
        item["bom-ref"] = f"{path.relative_to(ROOT)}:{package_path}"
        item["properties"].append({"name": "tierx:installation-path", "value": package_path})
        evidence = NPM_LICENSE_EVIDENCE.get(f"{name}@{meta['version']}")
        license_id = meta.get("license") or (evidence or {}).get("license")
        if not license_id:
            raise ValueError(f"No verified license for {name}@{meta['version']} in {path.relative_to(ROOT)}")
        item["licenses"] = [license_declaration(license_id)]
        if evidence:
            item["properties"].append({"name": "tierx:license-evidence", "value": evidence["source"]})
        result.append(item)
    return result


def python_components(path: Path) -> list[dict]:
    result = []
    requirements = (
        tomllib.loads(path.read_text())["project"].get("dependencies", [])
        if path.suffix == ".toml" else path.read_text().splitlines()
    )
    for line in requirements:
        requirement = line.strip()
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?([^;\s]*)", requirement)
        if not match or requirement.startswith(("#", "-")):
            continue
        name, constraint = match.groups()
        normalized_name = name.lower().replace("_", "-")
        evidence = PYTHON_LICENSE_EVIDENCE.get(normalized_name)
        if not evidence:
            raise ValueError(f"No verified license for Python requirement {name} in {path.relative_to(ROOT)}")
        properties = [
            {"name": "tierx:manifest", "value": str(path.relative_to(ROOT))},
            {"name": "tierx:requirement", "value": requirement},
            {"name": "tierx:license-evidence", "value": evidence["source"]},
        ]
        result.append({
            "type": "library", "name": name,
            "purl": f"pkg:pypi/{normalized_name}",
            "licenses": [license_declaration(evidence["license"])],
            "properties": properties,
        })
        if re.fullmatch(r"==[^*,<>=!~]+", constraint):
            version = constraint[2:]
            result[-1]["version"] = version
            result[-1]["purl"] += f"@{quote(version, safe='')}"
    return result


def main() -> None:
    components = [item for path in LOCKS for item in npm_components(path)]
    components += [item for path in (*REQUIREMENTS, *PYPROJECTS) for item in python_components(path)]
    components.sort(key=lambda value: (value["name"].lower(), value.get("version", ""), value["purl"], value["properties"][0]["value"], value.get("bom-ref", "")))
    manifest_hash = hashlib.sha256("".join(path.read_text() for path in (*LOCKS, *REQUIREMENTS, *PYPROJECTS)).encode()).hexdigest()
    sbom = {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "TierX", "version": "source", "licenses": [{"license": {"id": "AGPL-3.0-only"}}]},
            "properties": [{"name": "tierx:manifest-sha256", "value": manifest_hash}],
        },
        "components": components,
    }
    (ROOT / "sbom.cdx.json").write_text(
        json.dumps(sbom, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    rows = [
        "# Third-party notices", "", "Generated by `tools/generate_license_artifacts.py` from dependency manifests.",
        "TierX's AGPL license does not replace dependency licenses. npm licenses are taken from integrity-locked package metadata, and direct Python requirement licenses are recorded from authoritative package metadata. Explicit evidence is retained when a manifest omits its license field.", "",
        "| Component | Version | Resolved license | Manifest |", "| --- | --- | --- | --- |",
    ]
    for item in components:
        licenses = ", ".join(license_text(value) for value in item.get("licenses", [])) or "Not applicable"
        rows.append(f"| `{item['name']}` | `{item.get('version', 'Not resolved')}` | {licenses} | `{item['properties'][0]['value']}` |")
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
