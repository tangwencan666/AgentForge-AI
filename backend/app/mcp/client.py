"""Bounded MCP stdio client for the single server-owned executable."""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from uuid import uuid4
from app.core.config import ROOT
from app.schemas.tools import AUDIENCE, CATALOG, PROTOCOL_VERSION, public_catalog
from app.services.context import content_hash

MAX_MESSAGE = 65536


def capability(token, tool, arguments, tenant, call_id, operation_hash):
    claims = {"aud": AUDIENCE, "tool": tool, "tenant": str(tenant), "call_id": str(call_id),
              "arguments_hash": content_hash(arguments), "operation_hash": operation_hash, "expires": int(time.time()) + 30}
    claims["signature"] = hmac.new(token.encode(), json.dumps(claims, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    return claims


class MCPClient:
    def __init__(self, settings):
        self.settings = settings

    def environment(self):
        # Do not inherit admin/approver/model credentials, proxy variables or Python startup hooks.
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP") if k in os.environ}
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
                    "AGENTFORGE_MCP_DATABASE_URL": self.settings.database_url.get_secret_value(),
                    "AGENTFORGE_MCP_SERVER_TOKEN": self.settings.mcp_server_token.get_secret_value()})
        return env

    async def call(self, tool, arguments, tenant, call_id, operation_hash):
        if tool not in CATALOG:
            raise ValueError("unknown tool")
        process = await asyncio.create_subprocess_exec(sys.executable, "-I", "-m", "app.mcp.server", cwd=str(ROOT),
            env=self.environment(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=MAX_MESSAGE)
        try:
            async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                await self.initialize(process)
                claims = capability(self.settings.mcp_server_token.get_secret_value(), tool, arguments, tenant, call_id, operation_hash)
                result = await self.rpc(process, "tools/call", {"name": tool, "arguments": arguments, "_meta": {"agentforge/capability": claims}})
                if result.get("isError") is not False or not isinstance(result.get("structuredContent"), dict):
                    raise ValueError("tool failed")
                return result["structuredContent"]
        finally:
            # Unknown remote outcome is reconciled via durable receipts, never retried here.
            if process.returncode is None:
                try:
                    process.stdin.close()
                    await asyncio.wait_for(process.wait(), timeout=.5)
                except (TimeoutError, BrokenPipeError, ConnectionResetError):
                    if process.returncode is None:
                        process.kill()
                    await process.wait()

    async def initialize(self, process):
        result = await self.rpc(process, "initialize", {"protocolVersion": PROTOCOL_VERSION,
            "capabilities": {}, "clientInfo": {"name": "agentforge-gateway", "version": "1.0.0"}})
        if result.get("protocolVersion") != PROTOCOL_VERSION or "tools" not in result.get("capabilities", {}):
            raise ValueError("protocol negotiation failed")
        await self.send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = await self.rpc(process, "tools/list", {})
        expected = [{k: v for k, v in item.items() if k in {"name", "description", "inputSchema", "outputSchema"}} for item in public_catalog()]
        if tools.get("tools") != expected:
            raise ValueError("discovered tool schema differs from the server allowlist")

    async def send(self, process, message):
        data = json.dumps(message, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        if len(data) > MAX_MESSAGE:
            raise ValueError("MCP request too large")
        process.stdin.write(data)
        await process.stdin.drain()

    async def rpc(self, process, method, params):
        request_id = uuid4().hex
        await self.send(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        line = await process.stdout.readline()
        if not line or len(line) > MAX_MESSAGE:
            raise ValueError("MCP response too large or missing")
        response = json.loads(line)
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id or "error" in response or not isinstance(response.get("result"), dict):
            raise ValueError("invalid MCP response")
        return response["result"]
