"""Cached, anonymous checks of TierX's published stable GitHub release."""
import asyncio
import os
import re
import time
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

REPOSITORY_URL = "https://github.com/Samimi-Tech-Consulting-GmbH/TierX"
LATEST_URL = "https://api.github.com/repos/Samimi-Tech-Consulting-GmbH/TierX/releases/latest"
VERSION_PATTERN = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", re.ASCII)


class LatestRelease(BaseModel):
    enabled: bool = True
    status: str
    latest_version: str | None = None
    release_url: str | None = None
    checked_at: datetime | None = None


class ReleaseService:
    def __init__(self, fetch=None, clock=time.monotonic):
        self._fetch = fetch or self._fetch_github
        self._clock = clock
        self._lock = asyncio.Lock()
        self._cached = None
        self._expires_at = 0

    @staticmethod
    async def _fetch_github():
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False, trust_env=False) as client:
            response = await client.get(LATEST_URL, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "TierX-release-check",
                "X-GitHub-Api-Version": "2022-11-28",
            })
            response.raise_for_status()
            return response.json()

    async def latest(self):
        if os.getenv("TIERX_UPDATE_CHECK_ENABLED", "true").lower() in {"false", "0", "no", "off"}:
            return LatestRelease(enabled=False, status="DISABLED")
        async with self._lock:
            if self._cached is not None and self._clock() < self._expires_at:
                return self._cached
            checked_at = datetime.now(timezone.utc)
            result = LatestRelease(status="UNAVAILABLE", checked_at=checked_at)
            try:
                payload = await asyncio.wait_for(self._fetch(), timeout=5.0)
                tag = payload.get("tag_name", "")
                if (isinstance(tag, str) and VERSION_PATTERN.fullmatch(tag)
                        and payload.get("draft") is False
                        and payload.get("prerelease") is False):
                    result = LatestRelease(
                        status="AVAILABLE", latest_version=tag.removeprefix("v"),
                        # Build the trusted URL rather than reflect an upstream link.
                        release_url=f"{REPOSITORY_URL}/releases/tag/{tag}",
                        checked_at=checked_at,
                    )
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
                pass
            self._cached = result
            self._expires_at = self._clock() + 3600
            return result


release_service = ReleaseService()
