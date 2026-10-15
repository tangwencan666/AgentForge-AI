"""Shared trusted checks used by Gateway and controlled MCP Server."""
from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import ValidationError
from sqlalchemy import select, text
from app.core.errors import AppError
from app.domain.tools import CapabilityApproval, CapabilityAudit, SkillVersion, ToolPermission
from app.schemas.tools import CATALOG, POLICY_VERSION, SkillManifest
from app.services.context import content_hash


def now():
    return datetime.now(timezone.utc)


async def tenant_lock(session, tenant):
    # All permission, lifecycle, dispatch and side-effect transactions share this lock.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                          {"key": "p4:" + str(tenant)})


def audit(session, tenant, target, event, **details):
    session.add(CapabilityAudit(id=uuid4(), tenant_id=UUID(str(tenant)), target_id=str(target), event=event, details=details))


async def skill_row(session, tenant, skill_id, version):
    row = await session.get(SkillVersion, (UUID(str(tenant)), skill_id, version))
    if row is None:
        raise AppError("SKILL_NOT_FOUND", "Skill version not found", 404)
    try:
        manifest = SkillManifest.model_validate(row.manifest)
    except ValidationError:
        raise AppError("SKILL_INTEGRITY", "Skill manifest is invalid", 409) from None
    if content_hash(manifest.model_dump()) != row.content_hash:
        raise AppError("SKILL_INTEGRITY", "Skill content changed", 409)
    return row


async def skill_tree(session, tenant, root, require_enabled=False):
    visited, active, result = set(), set(), []

    async def walk(row, depth):
        key = (row.skill_id, row.version)
        if key in active or depth > 8 or len(visited) >= 32:
            raise AppError("SKILL_DEPENDENCY_INVALID", "Dependency closure is cyclic or too large", 409)
        if key in visited:
            return
        active.add(key)
        for dep in row.manifest["dependencies"]:
            child = await skill_row(session, tenant, dep["skill_id"], dep["version"])
            if child.content_hash != dep["content_hash"]:
                raise AppError("SKILL_DEPENDENCY_CHANGED", "Dependency hash changed", 409)
            allowed = {"enabled"} if require_enabled else {"installed_disabled", "pending_enable", "enabled", "disabled"}
            if child.status not in allowed or child.installed_hash != child.content_hash:
                raise AppError("SKILL_DEPENDENCY_INACTIVE", "Dependencies must be installed and, for enable/use, enabled", 409)
            await walk(child, depth + 1)
        active.remove(key)
        visited.add(key)
        result.append(row)

    await walk(root, 0)
    return result


def tree_snapshot(tree):
    return [{"skill_id": r.skill_id, "version": r.version, "content_hash": r.content_hash, "generation": r.generation}
            for r in sorted(tree, key=lambda r: (r.skill_id, r.version))]


async def enabled_skill(session, tenant, ref, tool):
    row = await skill_row(session, tenant, ref["skill_id"], ref["version"])
    if row.status != "enabled" or row.installed_hash != row.content_hash:
        raise AppError("SKILL_DISABLED", "Skill is not enabled", 403)
    tree = await skill_tree(session, tenant, row, require_enabled=True)
    # Every node binds the generations of its complete dependency closure.
    for node in tree:
        closure = await skill_tree(session, tenant, node, require_enabled=True)
        if node.enabled_hash != content_hash(tree_snapshot([r for r in closure if r is not node])):
            raise AppError("SKILL_DEPENDENCY_CHANGED", "Dependency lifecycle changed; enable approval is required again", 409)
    if tool not in row.manifest["tools"] or CATALOG[tool]["permission"] not in row.manifest["required_permissions"]:
        raise AppError("SKILL_PERMISSION_DENIED", "Tool is outside the Skill permission declaration", 403)
    return tree_snapshot(tree)


def operation_digest(row, skill_snapshot=None):
    return content_hash({"tenant": str(row.tenant_id), "tool": row.tool, "version": row.tool_version,
                         "resource": row.resource, "arguments": row.arguments, "skill": skill_snapshot,
                         "permission_generation": row.permission_generation, "policy": row.policy_version,
                         "requester": row.requester})


async def authorize_call(session, row):
    if row.policy_version != POLICY_VERSION or row.tool not in CATALOG or row.tool_version != CATALOG[row.tool]["version"]:
        raise AppError("TOOL_POLICY_CHANGED", "Tool policy changed", 409)
    try:
        args = CATALOG[row.tool]["input"].model_validate(row.arguments).model_dump()
    except ValidationError:
        raise AppError("TOOL_SCHEMA_INVALID", "Tool arguments do not match the schema", 422) from None
    if args["resource"] != row.resource:
        raise AppError("TOOL_RESOURCE_MISMATCH", "Resource binding changed", 409)
    grant = await session.get(ToolPermission, (row.tenant_id, row.tool, row.resource))
    if not grant or not grant.allowed or grant.generation != row.permission_generation:
        raise AppError("TOOL_FORBIDDEN", "Current resource permission is required", 403)
    snapshot = await enabled_skill(session, row.tenant_id, row.skill, row.tool) if row.skill else None
    if row.operation_hash != operation_digest(row, snapshot):
        raise AppError("APPROVAL_MISMATCH", "Bound tool parameters or Skill version changed", 409)
    if CATALOG[row.tool]["high_risk"]:
        approval = await session.get(CapabilityApproval, row.approval_id) if row.approval_id else None
        if (not approval or approval.tenant_id != row.tenant_id or approval.target_id != str(row.id)
                or approval.action != "tool.execute" or approval.operation_hash != row.operation_hash
                or approval.policy_version != POLICY_VERSION or approval.status != "approved"
                or approval.expires_at <= now() or approval.requester != row.requester
                or not approval.decided_by or approval.decided_by == row.requester):
            raise AppError("TOOL_APPROVAL_REQUIRED", "Independent unexpired approval is required", 403)
    return args
