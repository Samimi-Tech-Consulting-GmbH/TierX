"""Editable examples, not mandatory pipeline policy or installed integrations."""
from copy import deepcopy


def linear(nodes, subflow=False):
    for index, node in enumerate(nodes):
        node.setdefault("position", {"x": index * 240, "y": 80})
    return {"format_version": "2.0", "input_capabilities": ["normalization" if subflow else "raw"],
            "nodes": nodes, "edges": [{"id": f"e{i}", "source": a["id"], "target": b["id"]}
                                      for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}


def node(identity, kind, **configuration):
    return {"id": identity, "type": kind, "config": configuration}


def templates():
    result = []
    generic = linear([node("entry", "entry"), node("kb", "kb_deterministic", top_k=5),
        node("analysis", "llm_analysis", profile_code="local-analysis", input_scope="alert"),
        node("save", "persist_analysis", input_path="nodes.analysis.output"),
        node("done", "complete", output_path="nodes.analysis.output.result")], True)
    result.append({"kind": "playbook", "code": "generic-triage", "name": "Generic evidence-based triage",
                   "description": "Fallback playbook: knowledge, analysis and alert-owned persistence.", "configuration": generic})
    entry = node("entry", "entry", input_mode="raw", source_system="SPLUNK", alert_type="endpoint.malware", timestamp_path="result._time")
    mapping = node("map", "normalization", field_mapping={"host.name": "result.host", "source.ip": "result.src",
        "user.name": "result.user", "event.severity": "result.severity", "event.created": "result._time"})
    workflow = linear([entry, node("validate", "validation"), mapping, node("dedup", "fingerprint"),
        node("correlate", "correlation", group=None, lookback_hours=24, grouping_hours=24),
        node("choose", "playbook_selector", mode="static", mappings={}, candidates=["generic-triage"], fallback="generic-triage", threshold=0.7),
        node("done", "complete", output_path="nodes.choose.output.result")])
    result.append({"kind": "workflow", "code": "raw-alert-triage", "name": "Raw alert → playbook → stored analysis",
        "description": "Publish the generic playbook first; map source/schema/profile to your installation. Add an explicit notification node if wanted.", "configuration": workflow})
    for role in ["endpoint", "identity", "network", "siem", "knowledge", "correlation"]:
        result.append({"kind": "agent", "code": f"{role}-specialist", "name": f"{role.title()} specialist",
            "description": "Configure real approved tools before expecting external observations. This template does not install a connector.",
            "configuration": {"profile_code": "local-analysis", "input_scope": "alert", "prompt":
                f"Assess {role} evidence for the initiating alert. Use only supplied evidence and approved tools. State missing evidence and uncertainty; never invent observations.",
                "tools": ["alert_evidence"], "max_rounds": 5, "max_calls": 10,
                "output_schema": {"type": "object", "properties": {"findings": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"enum": ["HIGH", "MEDIUM", "LOW"]}}, "required": ["findings", "confidence"], "additionalProperties": False}}})
    return deepcopy(result)
