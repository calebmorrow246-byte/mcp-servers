"""
Unixi MCP Proxy (read-only)

Hosted front for Unixi's own beta MCP server (POST https://app.unixi.io/mcp). Callers authenticate to
this proxy with their per-user bearer token (see mcp_transport.py); the proxy adds the shared Unixi
X-API-KEY / X-TENANT-ID headers upstream, so users never hold the Unixi key.

Read-only by construction: only the tools in ALLOWED_TOOLS are listed or callable. Anything else
Unixi adds later (including any write tool) is hidden and rejected until it is added here on purpose.
derived.py adds computed tools (residual_access_report, shadow_app_gap) built only from those same
allow-listed upstream tools.

Configuration via environment variables:
  UNIXI_API_KEY    - Unixi key with purpose "MCP API" (required)
  UNIXI_TENANT_ID  - Unixi tenant GUID (required)
  UNIXI_BASE_URL   - Upstream base URL (default: https://app.unixi.io)
  UNIXI_TIMEOUT    - Request timeout in seconds (default: 60)
"""

import json
import os
import sys
from typing import Any

import httpx
from starlette.responses import JSONResponse, Response

from derived import DERIVED_NAMES, DERIVED_TOOLS, run_derived
from mcp_transport import run_asgi

# The 7 read-only tools Unixi exposed on 2026-10-23; each mirrors a GET /api/public/v1/* endpoint
ALLOWED_TOOLS = frozenset({
    "get_logs",
    "get_applications",
    "get_discovery_shared_accounts",
    "get_discovery_applications",
    "get_lifecycle_applications",
    "get_lifecycle_app_tenants",
    "get_lifecycle_users",
})

SERVER_NAME = "Unixi"
FALLBACK_PROTOCOL = "2025-03-26"


class _Upstream:
    """Forwards a JSON-RPC message to Unixi's /mcp endpoint and returns the parsed JSON response."""

    def __init__(self) -> None:
        self.key = os.environ.get("UNIXI_API_KEY", "")
        self.tenant = os.environ.get("UNIXI_TENANT_ID", "").strip()
        if not self.key or not self.tenant:
            raise SystemExit("UNIXI_API_KEY and UNIXI_TENANT_ID are required")
        base = os.environ.get("UNIXI_BASE_URL", "https://app.unixi.io").rstrip("/")
        self.url = f"{base}/mcp"
        self.client = httpx.AsyncClient(timeout=float(os.environ.get("UNIXI_TIMEOUT", "60")))

    async def call(self, message: dict) -> Any:
        response = await self.client.post(
            self.url,
            json=message,
            headers={
                "X-API-KEY": self.key,
                "X-TENANT-ID": self.tenant,
                "Accept": "application/json, text/event-stream",
            },
        )
        response.raise_for_status()
        return _parse_body(response)

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call one allow-listed upstream tool and return its parsed JSON body (for derived tools)."""
        if name not in ALLOWED_TOOLS:
            raise ValueError(f"Not an allowed upstream tool: {name}")
        reply = await self.call({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": name, "arguments": arguments}})
        result = reply.get("result", {}) if isinstance(reply, dict) else {}
        if result.get("isError") or "error" in (reply or {}):
            raise ValueError(f"Upstream tool {name} returned an error")
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except ValueError:
                    break
        raise ValueError(f"Upstream tool {name} returned an unreadable body")


def _parse_body(response: httpx.Response) -> Any:
    """Return the JSON-RPC payload from a plain JSON or an SSE (data: lines) response."""
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    return json.loads(payload)
        raise ValueError("Upstream SSE response contained no data")
    return response.json()


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


async def _handle(message: Any, upstream: _Upstream) -> dict | None:
    """Answer one JSON-RPC message; returns None for notifications (no response)."""
    if not isinstance(message, dict) or "method" not in message:
        return _error(None, -32600, "Invalid request")
    method = message["method"]
    msg_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if msg_id is None:  # notification, e.g. notifications/initialized
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": params.get("protocolVersion", FALLBACK_PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        reply = await upstream.call({"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}})
        tools = reply.get("result", {}).get("tools", []) if isinstance(reply, dict) else []
        allowed = [t for t in tools if t.get("name") in ALLOWED_TOOLS]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": allowed + DERIVED_TOOLS}}
    if method == "tools/call":
        if params.get("name") in DERIVED_NAMES:
            try:
                text = await run_derived(params["name"], params.get("arguments"), upstream.call_tool)
            except ValueError as exc:  # argument validation or an unreadable upstream body
                return _error(msg_id, -32602, str(exc))
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": text}]}}
        if params.get("name") not in ALLOWED_TOOLS:
            return _error(msg_id, -32602, f"Unknown tool: {params.get('name')}")
        reply = await upstream.call({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": params})
        return reply if isinstance(reply, dict) else _error(msg_id, -32603, "Bad upstream response")
    return _error(msg_id, -32601, f"Method not found: {method}")


class _ProxyApp:
    """ASGI app for /mcp (POST JSON-RPC) and /health. Auth and audit are applied by the middleware."""

    def __init__(self) -> None:
        self.upstream = _Upstream()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        path, method = scope["path"], scope["method"]
        if path == "/health" and method == "GET":
            response: Response = JSONResponse({"status": "ok", "server": SERVER_NAME})
        elif path.rstrip("/") == "/mcp" and method == "POST":
            response = await self._rpc(receive)
        elif path.rstrip("/") == "/mcp":
            response = Response(status_code=405, headers={"Allow": "POST"})  # stateless: no SSE stream
        else:
            response = Response(status_code=404)
        await response(scope, receive, send)

    async def _rpc(self, receive: Any) -> Response:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        try:
            parsed = json.loads(body)
        except ValueError:
            return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
        batch = parsed if isinstance(parsed, list) else [parsed]
        replies = []
        for item in batch:
            try:
                reply = await _handle(item, self.upstream)
            except httpx.HTTPStatusError as exc:
                # Surface the status only; never echo the upstream body or any credential
                reply = _error(item.get("id") if isinstance(item, dict) else None, -32000,
                               f"Unixi returned HTTP {exc.response.status_code}")
            except Exception as exc:
                print(f"upstream failure: {type(exc).__name__}", file=sys.stderr, flush=True)
                reply = _error(item.get("id") if isinstance(item, dict) else None, -32000, "Unixi request failed")
            if reply is not None:
                replies.append(reply)
        if not replies:
            return Response(status_code=202)
        return JSONResponse(replies if isinstance(parsed, list) else replies[0])


if __name__ == "__main__":
    run_asgi(_ProxyApp(), SERVER_NAME)
