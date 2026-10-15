"""Trusted, fixed MCP stdio server. Never executes Skill/Agent supplied Python."""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from uuid import UUID
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from app.core.errors import AppError
from app.domain.tools import CapabilityApproval, ManagedNote, ToolCall
from app.schemas.tools import AUDIENCE, CATALOG, PROTOCOL_VERSION, public_catalog
from app.services.capabilities import audit, authorize_call, tenant_lock
from app.services.context import content_hash

MAX_MESSAGE = 65536


def verify_capability(claims, token, tool, arguments):
    if not isinstance(claims, dict):
        raise ValueError("missing capability")
    unsigned = {k: v for k, v in claims.items() if k != "signature"}
    expected = hmac.new(token.encode(), json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    if (not isinstance(claims.get("signature"), str) or not hmac.compare_digest(expected, claims["signature"])
            or claims.get("aud") != AUDIENCE or claims.get("tool") != tool
            or claims.get("arguments_hash") != content_hash(arguments)
            or type(claims.get("expires")) is not int or not time.time() < claims["expires"] <= time.time() + 60):
        raise ValueError("invalid capability")
    return UUID(claims["tenant"]), UUID(claims["call_id"])


async def invoke(sessions, token, params):
    tool, arguments = params.get("name"), params.get("arguments")
    if tool not in CATALOG:
        raise ValueError("unknown tool")
    arguments = CATALOG[tool]["input"].model_validate(arguments).model_dump()
    claims = params.get("_meta", {}).get("agentforge/capability")
    tenant, call_id = verify_capability(claims, token, tool, arguments)
    async with sessions() as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(text("SET LOCAL statement_timeout = '3s'"))
        await tenant_lock(session, tenant)
        verify_capability(claims, token, tool, arguments)
        row = await session.get(ToolCall, call_id)
        if not row or row.tenant_id != tenant or row.tool != tool or row.arguments != arguments or row.operation_hash != claims["operation_hash"]:
            raise ValueError("call binding mismatch")
        if row.status != "dispatched":
            raise ValueError("call has no active dispatch")
        # All checks are repeated in the same transaction as the managed side effect.
        await authorize_call(session, row)
        if row.remote_result is not None:
            raise ValueError("call already executed")
        resource = arguments["resource"]
        note = await session.get(ManagedNote, (tenant, resource))
        if tool == "notes.write":
            if note is None:
                note = ManagedNote(tenant_id=tenant, resource=resource, text=arguments["text"], revision=1)
                session.add(note)
            else:
                note.text, note.revision = arguments["text"], note.revision + 1
        result = {"resource": resource, "text": note.text if note else "", "revision": note.revision if note else 0, "found": note is not None}
        row.remote_result = result
        if row.approval_id:
            approval = await session.get(CapabilityApproval, row.approval_id)
            approval.status = "consumed"
        audit(session, tenant, call_id, "mcp_side_effect_committed", tool=tool, resource=resource, revision=result["revision"])
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result, "isError": False}


async def run():
    token = os.environ["AGENTFORGE_MCP_SERVER_TOKEN"]
    if len(token) < 32:
        raise ValueError("server authentication missing")
    engine = create_async_engine(os.environ["AGENTFORGE_MCP_DATABASE_URL"], echo=False, hide_parameters=True,
                                 connect_args={"timeout": 2}, pool_size=1, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    initialized, ready = False, False
    try:
        while True:
            # Bounded stdio framing. No payload or exception is written to logs.
            line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_MESSAGE + 1)
            if not line:
                return
            if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                return
            request_id = None
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError("invalid JSON-RPC")
                request_id = message.get("id")
                method, params = message.get("method"), message.get("params", {})
                if method == "initialize" and request_id is not None and not initialized:
                    if params.get("protocolVersion") != PROTOCOL_VERSION:
                        raise ValueError("unsupported protocol")
                    initialized = True
                    result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                              "serverInfo": {"name": "agentforge-controlled-mcp", "version": "1.0.0"}}
                elif method == "notifications/initialized" and initialized and request_id is None:
                    ready = True
                    continue
                elif ready and request_id is not None:
                    if method == "tools/list":
                        result = {"tools": [{k: v for k, v in item.items() if k in {"name", "description", "inputSchema", "outputSchema"}} for item in public_catalog()]}
                    elif method == "tools/call":
                        result = await invoke(sessions, token, params)
                    elif method == "ping":
                        result = {}
                    else:
                        raise ValueError("unsupported method")
                else:
                    raise ValueError("initialization required")
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
            except Exception as exc:
                code = exc.code if isinstance(exc, AppError) else "MCP_REQUEST_REJECTED"
                response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": code}}
            if request_id is not None:
                sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
                sys.stdout.buffer.flush()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception:
        raise SystemExit(1) from None
