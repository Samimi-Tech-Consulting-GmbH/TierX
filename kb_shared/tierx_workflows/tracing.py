"""Bounded debug evidence, never full prompts, raw alerts or credentials."""
from tierx_workflows.graph import canonical, checksum
from tierx_workflows.safety import sanitize


def debug_snapshot(value, maximum=32768):
    def clean(item):
        if isinstance(item, dict):
            if "python_call_id" in item:
                item = {key: value for key, value in item.items() if key != "result"}
            return {key: clean(child) for key, child in sanitize(item).items() if not (key == "context" and isinstance(child, str)) and key not in {
                "raw_payload", "prompt", "prompt_footer", "context_text", "text", "playbook_snapshot", "resources", "bundle"}}
        if isinstance(item, list):
            return [clean(child) for child in item]
        return item
    result = clean(value)
    size = len(canonical(result))
    return {"value": result if size <= maximum else None, "size_bytes": size,
            "sha256": checksum(result), "omitted": size > maximum}
