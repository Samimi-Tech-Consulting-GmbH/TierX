"""Remove known credential-bearing fields before evidence leaves the worker."""

from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def sensitive(name):
    name = str(name).lower().replace("-", "_")
    return (
        any(
            part in name
            for part in (
                "password",
                "secret",
                "authorization",
                "credential",
                "api_key",
                "cookie",
            )
        )
        or name
        in {
            "token",
            "jwt",
            "access_token",
            "refresh_token",
            "mongo_url",
            "database_url",
        }
        or name.endswith("_token")
    )


def sanitize(value):
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if sensitive(k) else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        if value.startswith(
            ("mongodb://", "mongodb+srv://", "postgres://", "postgresql://")
        ):
            return "[REDACTED DATABASE URL]"
        if value.startswith("eyJ") and value.count(".") == 2:
            return "[REDACTED TOKEN]"
        if value.startswith(("http://", "https://")):
            try:
                parts = urlsplit(value)
                if parts.username or parts.password:
                    return "[REDACTED CREDENTIAL URL]"
                query = urlencode(
                    [
                        (k, "[REDACTED]" if sensitive(k) else v)
                        for k, v in parse_qsl(parts.query)
                    ]
                )
                return urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
                )
            except ValueError:
                return "[INVALID URL]"
    return value
