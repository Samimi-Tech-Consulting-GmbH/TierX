"""Installation and runtime configuration shared by TierX services."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import urlsplit

DEFAULTS = {
    "public_url": "http://localhost:8080",
    "ollama_url": "http://ollama:11434",
    "ollama_model": "phi3:latest",
    "llm_analysis_enabled": False,
    "correlation_enabled": False,
    "knowledge_base_processing_enabled": False,
    "knowledge_base_retrieval_enabled": False,
}
BOOLEAN_FIELDS = {key for key, value in DEFAULTS.items() if isinstance(value, bool)}
COLLECTION = "platform_configuration"
IDENTITY = "installation"


def env_value(name, environ=None):
    env = os.environ if environ is None else environ
    for key in (f"TIERX_{name.upper()}", name.upper(), f"SOC_MIND_{name.upper()}"):
        if key in env and env[key] != "":
            return env[key]
    return None


def boolean(value):
    if isinstance(value, bool):
        return value
    if str(value).lower() in {"true", "1", "yes", "on"}:
        return True
    if str(value).lower() in {"false", "0", "no", "off"}:
        return False
    raise ValueError("Expected a boolean value")


def validate(values):
    result = {**DEFAULTS, **values}
    if set(result) - set(DEFAULTS):
        raise ValueError("Unknown platform setting")
    for key in BOOLEAN_FIELDS:
        result[key] = boolean(result[key])
    for key in ("public_url", "ollama_url"):
        url = str(result[key]).strip().rstrip("/")
        if any(ord(character) < 32 or ord(character) == 127 for character in url):
            raise ValueError(f"Invalid control character in {key}")
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in {"", "/"}):
            raise ValueError(f"{key} must be an HTTP(S) origin without credentials or a path")
        try:
            parts.port
        except ValueError as exc:
            raise ValueError(f"Invalid port in {key}") from exc
        if key == "public_url" and parts.scheme == "http" and parts.hostname not in {
            "localhost", "127.0.0.1", "::1"
        }:
            raise ValueError("public_url requires HTTPS except on localhost")
        result[key] = url
    model = str(result["ollama_model"]).strip()
    if not model or len(model) > 256 or any(ch.isspace() for ch in model):
        raise ValueError("ollama_model must be a nonempty model name")
    result["ollama_model"] = model
    if result["llm_analysis_enabled"] and not result["correlation_enabled"]:
        raise ValueError("Analysis requires correlation")
    return result


def effective(saved=None, environ=None):
    values = {**DEFAULTS, **(saved or {})}
    locked = []
    for key in DEFAULTS:
        override = env_value(key, environ)
        if override is not None:
            values[key] = boolean(override) if key in BOOLEAN_FIELDS else override
            locked.append(key)
    return validate(values), locked


def installed(document):
    return bool(document and document.get("state") == "INSTALLED")


def heartbeat(service, revision, error=None):
    return {"service": service, "applied_revision": revision,
            "seen_at": datetime.now(timezone.utc), "configuration_error": error}


class RuntimeSettings:
    """A job-local snapshot over otherwise immutable deployment settings."""
    def __init__(self, base):
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "values", {})
        object.__setattr__(self, "revision", 0)
        object.__setattr__(self, "local", ContextVar("tierx_settings", default=None))

    def __getattr__(self, key):
        values = self.local.get()
        return (self.values if values is None else values).get(key, getattr(self.base, key, None))

    def __setattr__(self, key, value):
        if key in {"values", "revision"}:
            object.__setattr__(self, key, value)
        else:
            setattr(self.base, key, value)

    @contextmanager
    def capture(self, values=None):
        snapshot = dict(self.values if values is None else values)
        token = self.local.set(snapshot)
        try:
            yield snapshot
        finally:
            self.local.reset(token)
