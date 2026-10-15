"""Fail-closed tool preparation, durable dispatch and independent approvals."""
import json
from datetime import timedelta
from uuid import UUID, uuid4
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.core.errors import AppError
from app.domain.tools import CapabilityApproval, CapabilityAudit, ToolCall, ToolDailyUsage, ToolPermission
from app.schemas.tools import CATALOG, POLICY_VERSION, NoteResult
from app.services.context import content_hash, redact
from app.services.capabilities import audit, authorize_call, enabled_skill, now, operation_digest, tenant_lock


def call_dto(row):
    return {"call_id": str(row.id), "tool": row.tool, "tool_version": row.tool_version, "resource": row.resource,
            "arguments": row.arguments, "skill": row.skill, "status": row.status, "operation_hash": row.operation_hash,
            "policy_version": row.policy_version, "approval_id": str(row.approval_id) if row.approval_id else None,
            "result": row.result, "error_code": row.error_code, "is_mock": False, "created_at": row.created_at.isoformat()}


def approval_dto(row):
    return {"approval_id": str(row.id), "target_id": row.target_id, "action": row.action,
            "operation_hash": row.operation_hash, "policy_version": row.policy_version, "status": row.status,
            "expires_at": row.expires_at.isoformat(), "requester": row.requester, "decided_by": row.decided_by}


class ToolGateway:
    def __init__(self, connections, settings):
        self.connections, self.settings = connections, settings

    async def refused(self, tenant, target, code):
        # Separate transaction survives the failed authorization transaction.
        async with self.connections.sessions() as session, session.begin():
            audit(session, tenant, target, "capability_denied", reason=code)

    async def permissions(self, tenant):
        async with self.connections.sessions() as session:
            rows = (await session.scalars(select(ToolPermission).where(ToolPermission.tenant_id == UUID(tenant)))).all()
            return [{"tool": r.tool, "resource": r.resource, "allowed": r.allowed, "generation": r.generation} for r in rows]

    async def permission(self, tenant, body):
        async with self.connections.sessions() as session, session.begin():
            await tenant_lock(session, tenant)
            row = await session.get(ToolPermission, (UUID(tenant), body.tool, body.resource))
            if row:
                if row.allowed != body.allowed:
                    row.generation += 1
                    row.allowed = body.allowed
            else:
                row = ToolPermission(tenant_id=UUID(tenant), tool=body.tool, resource=body.resource, allowed=body.allowed)
                session.add(row)
            audit(session, tenant, body.tool, "tool_permission_changed", resource=body.resource, allowed=body.allowed)
            await session.flush()
            return {"tool": row.tool, "resource": row.resource, "allowed": row.allowed, "generation": row.generation}

    async def create(self, tenant, key, body):
        try:
            return await self._create(tenant, key, body)
        except AppError as exc:
            await self.refused(tenant, body.tool, exc.code)
            raise

    async def _create(self, tenant, key, body, *, task_context=None):
        if not self.settings.mcp_server_token:
            raise AppError("MCP_UNAVAILABLE", "Controlled MCP Server is not configured", 503)
        spec = CATALOG[body.tool]
        try:
            args = spec["input"].model_validate(body.arguments).model_dump()
        except ValidationError:
            raise AppError("TOOL_SCHEMA_INVALID", "Tool arguments do not match the strict schema", 422) from None
        encoded = json.dumps(args, ensure_ascii=False)
        if redact(encoded, self.settings) != encoded:
            raise AppError("SENSITIVE_TOOL_ARGUMENTS", "Protected secret data cannot be sent to a tool", 422)
        digest = content_hash(body.model_dump())
        async with self.connections.sessions() as session, session.begin():
            await tenant_lock(session, tenant)
            old = (await session.scalars(select(ToolCall).where(ToolCall.tenant_id == UUID(tenant), ToolCall.idempotency_key == key))).one_or_none()
            if old:
                if old.request_hash != digest:
                    raise AppError("IDEMPOTENCY_CONFLICT", "Idempotency key has another request", 409)
                return call_dto(old)
            grant = await session.get(ToolPermission, (UUID(tenant), body.tool, args["resource"]))
            if not grant or not grant.allowed:
                raise AppError("TOOL_FORBIDDEN", "Explicit resource permission is required", 403)
            ref = body.skill.model_dump() if body.skill else None
            snapshot = await enabled_skill(session, tenant, ref, body.tool) if ref else None
            row = ToolCall(id=uuid4(), tenant_id=UUID(tenant), idempotency_key=key, tool=body.tool,
                           tool_version=spec["version"], resource=args["resource"], arguments=args, request_hash=digest,
                           permission_generation=grant.generation, skill=ref, policy_version=POLICY_VERSION,
                           requester="local-admin", status="awaiting_approval" if spec["high_risk"] else "ready")
            row.task_context = task_context
            row.operation_hash = operation_digest(row, snapshot)
            if spec["high_risk"]:
                if not self.settings.capability_approver_token:
                    raise AppError("CAPABILITY_APPROVER_UNAVAILABLE", "Independent P4 approver is not configured", 503)
                approval = CapabilityApproval(id=uuid4(), tenant_id=UUID(tenant), target_id=str(row.id), action="tool.execute",
                    operation_hash=row.operation_hash, policy_version=POLICY_VERSION, expires_at=now() + timedelta(minutes=15))
                session.add(approval)
                row.approval_id = approval.id
            session.add(row)
            audit(session, tenant, row.id, "tool_prepared", tool=row.tool, operation_hash=row.operation_hash)
            await session.flush()
            return call_dto(row)

    async def get(self, tenant, call_id):
        async with self.connections.sessions() as session:
            return call_dto(await self._row(session, tenant, call_id))

    async def list(self, tenant):
        async with self.connections.sessions() as session:
            rows = (await session.scalars(select(ToolCall).where(ToolCall.tenant_id == UUID(tenant))
                                         .order_by(ToolCall.created_at.desc()).limit(100))).all()
            return [call_dto(row) for row in rows]

    async def _row(self, session, tenant, call_id):
        row = await session.get(ToolCall, call_id)
        if row is None or row.tenant_id != UUID(tenant):
            raise AppError("TOOL_CALL_NOT_FOUND", "Tool call not found", 404)
        return row

    async def execute(self, tenant, call_id):
        try:
            async with self.connections.sessions() as session, session.begin():
                await tenant_lock(session, tenant)
                row = await self._row(session, tenant, call_id)
                if row.status == "succeeded":
                    return call_dto(row)
                if row.status not in {"ready", "awaiting_approval"}:
                    raise AppError("TOOL_CALL_UNRESOLVED", "Dispatched calls cannot be replayed; inspect or reconcile", 409)
                await authorize_call(session, row)
                day = now().date()
                await session.execute(insert(ToolDailyUsage).values(tenant_id=UUID(tenant), day=day, calls=0).on_conflict_do_nothing())
                quota = await session.get(ToolDailyUsage, (UUID(tenant), day))
                if quota.calls >= self.settings.mcp_daily_call_limit:
                    raise AppError("TOOL_QUOTA_EXCEEDED", "Daily tool call quota exhausted", 409)
                quota.calls += 1
                row.status, row.dispatched_at = "dispatched", now()
                audit(session, tenant, row.id, "tool_dispatch_committed", operation_hash=row.operation_hash)
                args, tool, op_hash = row.arguments, row.tool, row.operation_hash
            # This boundary commits the intent and audit BEFORE starting a subprocess.
            from app.mcp.client import MCPClient
            try:
                result = await MCPClient(self.settings).call(tool, args, tenant, call_id, op_hash)
                result = NoteResult.model_validate(result).model_dump()
                if result["resource"] != args["resource"]:
                    raise ValueError("response binding")
                result = json.loads(redact(json.dumps(result, ensure_ascii=False), self.settings))
                error = None
            except Exception:
                # Cancellation/crash leaves 'dispatched'; timeout or unknown completion never retries.
                result, error = None, "MCP_RESULT_UNCERTAIN"
            async with self.connections.sessions() as session, session.begin():
                await tenant_lock(session, tenant)
                row = await self._row(session, tenant, call_id)
                # Require the controlled Server's transaction receipt, not only an RPC response.
                if error or row.remote_result != result:
                    row.status, row.error_code = "needs_reconciliation", error or "MCP_RECEIPT_MISMATCH"
                else:
                    row.status, row.result, row.finished_at = "succeeded", result, now()
                audit(session, tenant, row.id, "tool_result_recorded", status=row.status, reason=row.error_code)
                return call_dto(row)
        except AppError as exc:
            await self.refused(tenant, call_id, exc.code)
            raise

    async def reconcile(self, tenant, call_id):
        async with self.connections.sessions() as session, session.begin():
            await tenant_lock(session, tenant)
            row = await self._row(session, tenant, call_id)
            if row.status not in {"dispatched", "needs_reconciliation", "succeeded"}:
                raise AppError("TOOL_RECONCILIATION_INVALID", "Call has no dispatch to reconcile", 409)
            if row.remote_result is not None:
                try:
                    receipt = NoteResult.model_validate(row.remote_result).model_dump()
                    if receipt["resource"] != row.resource:
                        raise ValueError("receipt binding")
                    row.result = json.loads(redact(json.dumps(receipt, ensure_ascii=False), self.settings))
                    row.status, row.error_code, row.finished_at = "succeeded", None, now()
                except (ValidationError, ValueError):
                    row.status, row.error_code = "needs_reconciliation", "MCP_RECEIPT_INVALID"
            else:
                row.status, row.error_code = "needs_reconciliation", "MCP_RECEIPT_UNAVAILABLE"
            audit(session, tenant, row.id, "tool_reconciled", status=row.status)
            return call_dto(row)

    async def approvals(self, tenant):
        async with self.connections.sessions() as session:
            rows = (await session.scalars(select(CapabilityApproval).where(CapabilityApproval.tenant_id == UUID(tenant))
                                         .order_by(CapabilityApproval.created_at.desc()).limit(100))).all()
            return [approval_dto(row) for row in rows]

    async def review(self, tenant, approval_id):
        async with self.connections.sessions() as session:
            row = await session.get(CapabilityApproval, approval_id)
            if not row or row.tenant_id != UUID(tenant):
                raise AppError("APPROVAL_NOT_FOUND", "Approval not found", 404)
            data = approval_dto(row)
            if row.action == "tool.execute":
                data["target"] = call_dto(await self._row(session, tenant, UUID(row.target_id)))
            else:
                from app.services.capabilities import skill_row, skill_tree
                from app.services.skills import skill_dto
                skill_id, version = row.target_id.split("@")
                target = await skill_row(session, tenant, skill_id, version)
                data["target"] = skill_dto(target)
                data["dependency_closure"] = [skill_dto(dep) for dep in await skill_tree(session, tenant, target)]
            return data

    async def decide(self, tenant, approval_id, body):
        try:
            async with self.connections.sessions() as session, session.begin():
                await tenant_lock(session, tenant)
                row = await session.get(CapabilityApproval, approval_id)
                if not row or row.tenant_id != UUID(tenant):
                    raise AppError("APPROVAL_NOT_FOUND", "Approval not found", 404)
                if row.status != "pending" or row.expires_at <= now() or row.policy_version != POLICY_VERSION:
                    raise AppError("APPROVAL_INACTIVE", "Approval is no longer active", 409)
                if row.operation_hash != body.operation_hash:
                    raise AppError("APPROVAL_MISMATCH", "Approval hash changed", 409)
                row.status, row.decided_by, row.decided_at = body.decision, "capability-reviewer", now()
                if row.action.startswith("skill."):
                    from app.services.skills import apply_skill_decision
                    await apply_skill_decision(session, row, body.decision)
                elif row.action == "tool.execute":
                    call = await self._row(session, tenant, UUID(row.target_id))
                    if call.status != "awaiting_approval" or call.approval_id != row.id or call.operation_hash != row.operation_hash:
                        raise AppError("APPROVAL_MISMATCH", "Tool approval binding changed", 409)
                    if body.decision == "approved":
                        await authorize_call(session, call)
                        call.status = "ready"
                    else:
                        call.status, call.error_code = "rejected", "APPROVAL_REJECTED"
                else:
                    raise AppError("APPROVAL_MISMATCH", "Unknown approval action", 409)
                audit(session, tenant, row.target_id, "capability_approval_decided", decision=body.decision, action=row.action)
                return approval_dto(row)
        except AppError as exc:
            await self.refused(tenant, approval_id, exc.code)
            raise

    async def history(self, tenant):
        async with self.connections.sessions() as session:
            rows = (await session.scalars(select(CapabilityAudit).where(CapabilityAudit.tenant_id == UUID(tenant))
                                         .order_by(CapabilityAudit.created_at.desc()).limit(200))).all()
            return [{"id": str(r.id), "target_id": r.target_id, "event": r.event, "details": r.details,
                     "created_at": r.created_at.isoformat()} for r in rows]
