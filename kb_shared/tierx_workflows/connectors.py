"""Bounded REST and MCP JSON transport shared by API and execution workers."""

import asyncio
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator


class ConnectorError(ValueError):
    pass


def validate_schema(schema):
    Draft202012Validator.check_schema(schema)

    def walk(value):
        if isinstance(value, dict):
            if set(value) & {"$ref", "$dynamicRef", "pattern", "patternProperties"}:
                raise ConnectorError("UNSUPPORTED_SCHEMA_FEATURE")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)


async def destination(url):
    parts = urlsplit(url)
    # Explicit deployment-only origins permit isolated local example servers.
    # A model, tenant, or connector definition cannot grant this exemption.
    local = set(
        filter(None, os.getenv("TIERX_V2_LOCAL_CONNECTOR_ORIGINS", "").split(","))
    )
    origin = f"{parts.scheme}://{parts.netloc}"
    if (
        parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or not parts.hostname
    ):
        raise ConnectorError("INVALID_CONNECTOR_URL")
    if origin in local and parts.scheme in {"http", "https"}:
        return url, None, None
    if parts.scheme != "https":
        raise ConnectorError("HTTPS_REQUIRED")
    addresses = await asyncio.to_thread(
        socket.getaddrinfo, parts.hostname, parts.port or 443, 0, socket.SOCK_STREAM
    )
    ips = sorted({entry[4][0] for entry in addresses})
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ConnectorError("DESTINATION_NOT_PUBLIC")
    # Pin the resolved destination for the connection; preserve TLS SNI/Host.
    ip = f"[{ips[0]}]" if ":" in ips[0] else ips[0]
    endpoint = f"https://{ip}:{parts.port or 443}{parts.path or '/'}"
    return endpoint, parts.netloc, parts.hostname


class ConnectorClient:
    def __init__(self, config, credential=None, transport=None):
        self.config = config
        self.credential = credential
        self.transport = transport
        self.session = None
        self.counter = 0
        self.protocol = "2025-11-25"

    async def request(self, body, *, notification=False):
        try:
            async with asyncio.timeout(self.config.get("timeout_seconds", 30)):
                endpoint, host, sni = await destination(self.config["url"])
                headers = {
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                }
                if host:
                    headers["Host"] = host
                if self.credential:
                    headers["Authorization"] = f"Bearer {self.credential}"
                if self.config["kind"] == "mcp":
                    headers["MCP-Protocol-Version"] = self.protocol
                if self.session:
                    headers["Mcp-Session-Id"] = self.session
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=10, read=None, write=10, pool=10),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        endpoint,
                        json=body,
                        headers=headers,
                        extensions={"sni_hostname": sni} if sni else {},
                    ) as response:
                        if response.status_code not in (
                            {200, 202, 204} if notification else {200}
                        ):
                            raise ConnectorError("CONNECTOR_HTTP_FAILURE")
                        self.session = response.headers.get(
                            "Mcp-Session-Id", self.session
                        )
                        raw = bytearray()
                        is_sse = "text/event-stream" in response.headers.get(
                            "content-type", ""
                        )
                        async for block in response.aiter_bytes():
                            raw.extend(block)
                            if len(raw) > 256 * 1024:
                                raise ConnectorError("CONNECTOR_RESPONSE_TOO_LARGE")
                            if is_sse:
                                # A server may keep the stream open after the result.
                                # Return on the matching complete event, not stream EOF.
                                text = raw.decode(errors="replace").replace(
                                    "\r\n", "\n"
                                )
                                for event in text.split("\n\n")[:-1]:
                                    data = "\n".join(
                                        line[5:].lstrip()
                                        for line in event.splitlines()
                                        if line.startswith("data:")
                                    )
                                    if data:
                                        item = json.loads(data)
                                        if item.get("id") == body.get("id"):
                                            return item
                        if notification:
                            return {}
                        if "text/event-stream" in response.headers.get(
                            "content-type", ""
                        ):
                            # Bounded SSE response; select only the matching JSON-RPC ID.
                            for event in (
                                raw.decode().replace("\r\n", "\n").split("\n\n")
                            ):
                                data = "\n".join(
                                    line[5:].lstrip()
                                    for line in event.splitlines()
                                    if line.startswith("data:")
                                )
                                if data:
                                    item = json.loads(data)
                                    if item.get("id") == body.get("id"):
                                        return item
                            raise ConnectorError("MCP_RESPONSE_MISSING")
                        return json.loads(raw)
        except ConnectorError:
            raise
        except (TimeoutError, httpx.HTTPError, ValueError, OSError) as exc:
            raise ConnectorError("CONNECTOR_UNAVAILABLE_OR_INVALID") from exc

    async def rpc(self, method, params=None):
        self.counter += 1
        result = await self.request(
            {
                "jsonrpc": "2.0",
                "id": self.counter,
                "method": method,
                "params": params or {},
            }
        )
        if (
            not isinstance(result, dict)
            or result.get("id") != self.counter
            or "error" in result
            or "result" not in result
        ):
            raise ConnectorError("MCP_PROTOCOL_FAILURE")
        return result["result"]

    async def initialize(self):
        response = await self.rpc(
            "initialize",
            {
                "protocolVersion": self.protocol,
                "capabilities": {},
                "clientInfo": {"name": "TierX", "version": "0.1.0"},
            },
        )
        if response.get("protocolVersion") not in {
            "2025-03-26",
            "2025-06-18",
            "2025-11-25",
        }:
            raise ConnectorError("MCP_PROTOCOL_UNSUPPORTED")
        self.protocol = response["protocolVersion"]
        await self.request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, notification=True
        )

    async def discover(self):
        try:
            async with asyncio.timeout(self.config.get("timeout_seconds", 30)):
                return await self._discover()
        except TimeoutError as exc:
            raise ConnectorError("CONNECTOR_TIMEOUT") from exc

    async def _discover(self):
        await self.initialize()
        result = await self.rpc("tools/list")
        if result.get("nextCursor") or len(result.get("tools", [])) > 100:
            raise ConnectorError("MCP_CATALOG_TOO_LARGE")
        return result.get("tools", [])

    async def call(self, tool, arguments, delivery_id):
        try:
            async with asyncio.timeout(self.config.get("timeout_seconds", 30)):
                return await self._call(tool, arguments, delivery_id)
        except TimeoutError as exc:
            raise ConnectorError("CONNECTOR_TIMEOUT") from exc

    async def _call(self, tool, arguments, delivery_id):
        validate_schema(tool["input_schema"])
        if not Draft202012Validator(tool["input_schema"]).is_valid(arguments):
            raise ConnectorError("TOOL_ARGUMENTS_INVALID")
        if self.config["kind"] == "mcp":
            await self.initialize()
            response = await self.rpc(
                "tools/call",
                {
                    "name": tool["name"],
                    "arguments": arguments,
                    "_meta": {"tierx/delivery_id": delivery_id},
                },
            )
            if response.get("isError"):
                raise ConnectorError("TOOL_REPORTED_FAILURE")
            output = response.get("structuredContent")
            if output is None:
                texts = [
                    entry["text"]
                    for entry in response.get("content", [])
                    if entry.get("type") == "text"
                ]
                if len(texts) != 1:
                    raise ConnectorError("TOOL_STRUCTURED_OUTPUT_REQUIRED")
                output = json.loads(texts[0])
        else:
            output = await self.request(
                {
                    "tool": tool["name"],
                    "arguments": arguments,
                    "delivery_id": delivery_id,
                }
            )
        validate_schema(tool["output_schema"])
        if not Draft202012Validator(tool["output_schema"]).is_valid(output):
            raise ConnectorError("TOOL_OUTPUT_INVALID")
        return output
