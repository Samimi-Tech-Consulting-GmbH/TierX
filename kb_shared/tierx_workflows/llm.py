"""Explicit native/JSON-emulated protocols; no provider/model fallbacks."""

import json
import httpx
from jsonschema import Draft202012Validator


class ModelError(ValueError):
    pass


def validate_output(value, schema):
    Draft202012Validator.check_schema(schema)
    if not Draft202012Validator(schema).is_valid(value):
        raise ModelError("MODEL_OUTPUT_INVALID")
    return value


async def infer(profile, messages, *, api_key=None, schema=None, tools=None):
    payload = {"model": profile["model"], "messages": messages, "stream": False}
    if profile["provider"] == "ollama":
        payload["options"] = {
            "temperature": profile.get("temperature", 0),
            "num_predict": profile.get("max_tokens", 2048),
        }
        if schema:
            payload["format"] = schema
        if tools:
            payload["tools"] = tools
        path = "/api/chat" if tools else "/api/generate"
        if not tools:
            payload.pop("messages")
            payload["prompt"] = "\n\n".join(
                f"{m['role'].upper()}:\n{m.get('content', '')}" for m in messages
            )
    else:
        path = "/chat/completions"
        payload.update(
            temperature=profile.get("temperature", 0),
            max_tokens=profile.get("max_tokens", 2048),
        )
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "tierx_output",
                    "strict": True,
                    "schema": schema,
                },
            }
        if tools:
            payload["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(
            timeout=profile.get("timeout_seconds", 120),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                profile["base_url"].rstrip("/") + path,
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    raise ModelError("MODEL_HTTP_FAILURE")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 512 * 1024:
                        raise ModelError("MODEL_RESPONSE_TOO_LARGE")
        data = json.loads(raw)
        message = (
            (
                data["message"]
                if tools
                else {"role": "assistant", "content": data["response"]}
            )
            if profile["provider"] == "ollama"
            else data["choices"][0]["message"]
        )
        if tools and message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                function = call["function"]
                args = function["arguments"]
                calls.append(
                    {
                        "name": function["name"],
                        "arguments": (
                            json.loads(args) if isinstance(args, str) else args
                        ),
                        "id": call.get("id"),
                    }
                )
            return {"kind": "tool_calls", "calls": calls, "message": message}
        value = json.loads(message["content"])
        if schema:
            validate_output(value, schema)
        return {"kind": "final", "result": value, "message": message}
    except ModelError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise ModelError("MODEL_REQUEST_OR_OUTPUT_FAILURE") from exc
