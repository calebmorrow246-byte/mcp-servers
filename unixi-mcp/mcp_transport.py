"""Transport selection for this MCP server: stdio or Streamable HTTP."""

import hashlib
import hmac
import json
import os
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

MAX_BODY_BYTES = 4 * 1024 * 1024

# Per-user backend credential headers of the HTTP request being handled (empty in stdio mode)
_request_credentials: ContextVar[dict[str, str]] = ContextVar("mcp_request_credentials", default={})


def request_credential(header: str) -> str | None:
    """Return the caller's own backend credential sent in `header` on the current HTTP request.

    Only headers declared in run_server(credential_headers=...) are captured. Returns None in stdio
    mode or when the caller didn't send one, so the server falls back to its shared credential.
    """
    return _request_credentials.get().get(header.lower())


def run_server(mcp: MCPServer, credential_headers: tuple[str, ...] = ()) -> None:
    """Run the server on the transport selected by environment variables.

    MCP_TRANSPORT         stdio (default) - a local client launches this process and talks over stdin/stdout
                          http            - Streamable HTTP (stateless) at http://MCP_HOST:MCP_PORT/mcp
    MCP_HOST              bind address for http mode (default 127.0.0.1)
    MCP_PORT              port for http mode (required when MCP_TRANSPORT=http)
    MCP_AUTH_TOKENS_FILE  JSON list of per-user bearer token hashes (required when MCP_TRANSPORT=http):
                          { "tokens": [ { "user": "first.last", "sha256": "<hex of SHA-256(token)>" } ] }

    HTTP mode requires "Authorization: Bearer <token>" on every /mcp request, checks the token's
    SHA-256 against the tokens file (re-read whenever it changes, so revocation is immediate), and
    writes an audit line per request: user, JSON-RPC method, and tool name (never arguments).
    It has no TLS of its own; it binds to loopback by default and is published through the TLS
    front end. GET /health is unauthenticated and returns 200 for monitoring.

    credential_headers lists request headers that may carry the caller's own backend credential;
    tools read them with request_credential() (values are never logged). The audit line records
    cred=user when one is present, else cred=shared.
    """
    mode = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if mode == "stdio":
        mcp.run()
        return
    if mode != "http":
        raise SystemExit(f"Unsupported MCP_TRANSPORT '{mode}' (use 'stdio' or 'http')")

    try:
        port = int(os.environ["MCP_PORT"])
    except (KeyError, ValueError):
        raise SystemExit("MCP_PORT must be set to a valid port number when MCP_TRANSPORT=http")
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    tokens_file = os.environ.get("MCP_AUTH_TOKENS_FILE")
    if not tokens_file:
        raise SystemExit("MCP_AUTH_TOKENS_FILE must be set when MCP_TRANSPORT=http")
    tokens = _TokenStore(tokens_file)
    tokens.load()  # fail at startup, not on the first request, if the file is missing or malformed

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": mcp.name})

    app = mcp.streamable_http_app(stateless_http=True, host=host)
    _log(mcp.name, f"running (Streamable HTTP) on http://{host}:{port}/mcp")
    middleware = _AuthMiddleware(app, tokens, mcp.name, tuple(h.lower() for h in credential_headers))
    uvicorn.run(middleware, host=host, port=port, log_level="warning")


def run_asgi(app: Any, name: str) -> None:
    """Serve a raw ASGI app (a proxy that speaks JSON-RPC itself) behind the same bearer auth and audit.

    Same environment variables as run_server, HTTP only: there is no stdio mode for the proxy.
    """
    if os.environ.get("MCP_TRANSPORT", "").lower() != "http":
        raise SystemExit("This server runs over Streamable HTTP only: set MCP_TRANSPORT=http")
    try:
        port = int(os.environ["MCP_PORT"])
    except (KeyError, ValueError):
        raise SystemExit("MCP_PORT must be set to a valid port number")
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    tokens_file = os.environ.get("MCP_AUTH_TOKENS_FILE")
    if not tokens_file:
        raise SystemExit("MCP_AUTH_TOKENS_FILE must be set")
    tokens = _TokenStore(tokens_file)
    tokens.load()
    _log(name, f"running (Streamable HTTP proxy) on http://{host}:{port}/mcp")
    uvicorn.run(_AuthMiddleware(app, tokens, name), host=host, port=port, log_level="warning")


class _TokenStore:
    """Per-user bearer token hashes from MCP_AUTH_TOKENS_FILE, reloaded when the file changes."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.entries: list[tuple[str, bytes]] = []
        self.loaded_mtime = -1.0

    def load(self) -> None:
        mtime = os.stat(self.path).st_mtime
        if mtime == self.loaded_mtime:
            return
        with open(self.path, encoding="utf-8-sig") as f:
            data = json.load(f)
        self.entries = [
            (t["user"], bytes.fromhex(t["sha256"]))
            for t in data.get("tokens", [])
            if t.get("user") and re.fullmatch(r"[0-9a-fA-F]{64}", t.get("sha256", ""))
        ]
        self.loaded_mtime = mtime

    def authenticate(self, header: str | None) -> str | None:
        """Return the user name for a valid "Bearer <token>" header, otherwise None."""
        match = re.fullmatch(r"Bearer\s+(\S+)", header or "", re.IGNORECASE)
        if not match:
            return None
        self.load()
        presented = hashlib.sha256(match.group(1).encode()).digest()
        # Compare against every entry so timing doesn't reveal which (if any) matched
        user = None
        for name, digest in self.entries:
            if hmac.compare_digest(presented, digest) and user is None:
                user = name
        return user


class _AuthMiddleware:
    """ASGI middleware: bearer-token check and audit logging for /mcp; everything else passes through."""

    def __init__(self, app: Any, tokens: _TokenStore, name: str, credential_headers: tuple[str, ...] = ()) -> None:
        self.app = app
        self.tokens = tokens
        self.name = name
        self.credential_headers = credential_headers

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        # Behind the TLS front end every connection comes from loopback; log the forwarded client instead
        client = scope.get("client")
        source = headers.get("x-forwarded-for", "").split(",")[0].strip() or (client[0] if client else "?")

        try:
            user = self.tokens.authenticate(headers.get("authorization"))
        except Exception as error:  # tokens file missing/unreadable
            _log(self.name, f"auth unavailable: {error}")
            await _send_json(send, 503, _rpc_error("Authentication unavailable"))
            return
        if user is None:
            _log(self.name, f"audit user=- status=401 from={source}")
            await _send_json(send, 401, _rpc_error("Unauthorized"), [(b"www-authenticate", b'Bearer realm="mcp"')])
            return

        # Buffer the body so it can be audited, then replay it to the MCP app
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > MAX_BODY_BYTES:
                await _send_json(send, 413, _rpc_error("Request body too large"))
                return
            if not message.get("more_body", False):
                break
        # Per-user backend credentials (only the headers this server declares; values never logged)
        credentials = {h: headers[h].strip() for h in self.credential_headers if headers.get(h, "").strip()}
        cred_kind = "" if not self.credential_headers else (" cred=user" if credentials else " cred=shared")
        _log(self.name, f"audit user={user} from={source}{cred_kind} {_describe(body)}")

        replayed = False

        async def replay() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        context_token = _request_credentials.set(credentials)
        try:
            await self.app(scope, replay, send)
        finally:
            _request_credentials.reset(context_token)


def _describe(body: bytes) -> str:
    """Audit summary of a JSON-RPC message or batch: method and tool name only, never arguments."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return "method=?"
    parts = []
    for msg in parsed if isinstance(parsed, list) else [parsed]:
        method = msg.get("method", "?") if isinstance(msg, dict) else "?"
        tool = ""
        if method == "tools/call" and isinstance(msg.get("params"), dict):
            tool = f" tool={msg['params'].get('name', '?')}"
        parts.append(f"method={method}{tool}")
    return "; ".join(parts)


def _rpc_error(message: str) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": -32000, "message": message}, "id": None}


async def _send_json(send: Any, status: int, payload: dict, extra_headers: list | None = None) -> None:
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json")] + (extra_headers or []),
    })
    await send({"type": "http.response.body", "body": json.dumps(payload).encode()})


def _log(name: str, message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    print(f"{stamp} {name} {message}", file=sys.stderr, flush=True)
