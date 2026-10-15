"""Data-only installation: no network, package manager, import or install hook."""
from datetime import timedelta
from uuid import UUID, uuid4
from sqlalchemy import select
from app.core.errors import AppError
from app.domain.tools import CapabilityApproval, SkillVersion
from app.schemas.tools import CATALOG, POLICY_VERSION, SkillCandidate
from app.services.context import content_hash, redact
from app.services.capabilities import audit, now, skill_row, skill_tree, tenant_lock, tree_snapshot


def skill_dto(row):
    return {"skill_id": row.skill_id, "version": row.version, "content_hash": row.content_hash,
            "manifest": row.manifest, "source": row.source, "status": row.status,
            "generation": row.generation, "approval_id": str(row.approval_id) if row.approval_id else None,
            "installed_hash": row.installed_hash, "created_at": row.created_at.isoformat()}


async def lifecycle_digest(session, row, action):
    tree = await skill_tree(session, row.tenant_id, row, require_enabled=action == "skill.enable")
    deps = tree_snapshot([r for r in tree if r is not row])
    return content_hash({"tenant": str(row.tenant_id), "skill_id": row.skill_id, "version": row.version,
                         "content_hash": row.content_hash, "generation": row.generation,
                         "action": action, "dependencies": deps, "policy": POLICY_VERSION}), deps


class SkillRegistry:
    def __init__(self, connections, settings):
        self.connections, self.settings = connections, settings

    async def list(self, tenant):
        async with self.connections.sessions() as session:
            rows = (await session.scalars(select(SkillVersion).where(SkillVersion.tenant_id == UUID(tenant))
                                         .order_by(SkillVersion.created_at.desc()).limit(100))).all()
            return [skill_dto(row) for row in rows]

    async def candidate(self, tenant, body: SkillCandidate):
        manifest = body.manifest.model_dump()
        import json
        encoded = json.dumps(manifest, ensure_ascii=False)
        if redact(encoded, self.settings) != encoded:
            raise AppError("SENSITIVE_MANIFEST_REJECTED", "Manifest contains protected secret data", 422)
        # Permission declarations cannot add capabilities or network/package installation.
        if any(CATALOG[tool]["permission"] not in manifest["required_permissions"] for tool in manifest["tools"]):
            raise AppError("SKILL_PERMISSION_INVALID", "Declared permissions must cover the declared tools", 422)
        async with self.connections.sessions() as session, session.begin():
            await tenant_lock(session, tenant)
            old = await session.get(SkillVersion, (UUID(tenant), manifest["skill_id"], manifest["version"]))
            digest = content_hash(manifest)
            if old:
                if old.content_hash != digest or old.source != body.source:
                    raise AppError("SKILL_VERSION_IMMUTABLE", "Create a new version for changed content or provenance", 409)
                return skill_dto(old)
            row = SkillVersion(tenant_id=UUID(tenant), skill_id=manifest["skill_id"], version=manifest["version"],
                               manifest=manifest, content_hash=digest, source=body.source, status="candidate")
            session.add(row)
            audit(session, tenant, row.skill_id + "@" + row.version, "skill_candidate_registered", content_hash=digest, source=body.source)
            await session.flush()
            return skill_dto(row)

    async def action(self, tenant, skill_id, version, action):
        async with self.connections.sessions() as session, session.begin():
            await tenant_lock(session, tenant)
            row = await skill_row(session, tenant, skill_id, version)
            target = skill_id + "@" + version
            if action in {"disable", "revoke"}:
                if row.status == "revoked":
                    return skill_dto(row)
                if row.approval_id:
                    old = await session.get(CapabilityApproval, row.approval_id)
                    if old and old.status in {"pending", "approved"}:
                        old.status = "cancelled"
                row.status = "revoked" if action == "revoke" else ("disabled" if row.installed_hash else ("candidate" if row.status == "candidate" else "registered"))
                row.generation += 1
                row.enabled_hash = None
                audit(session, tenant, target, "skill_" + action)
            elif action == "register":
                if row.status != "candidate":
                    raise AppError("SKILL_STATE_INVALID", "Only a candidate can be registered", 409)
                row.status = "registered"
                row.generation += 1
                audit(session, tenant, target, "skill_registered", content_hash=row.content_hash)
            else:
                if not self.settings.capability_approver_token:
                    raise AppError("CAPABILITY_APPROVER_UNAVAILABLE", "Independent P4 approver is not configured", 503)
                allowed = {"registered"} if action == "install" else {"installed_disabled", "disabled"}
                if row.status not in allowed:
                    raise AppError("SKILL_STATE_INVALID", "Skill action is not allowed in its current state", 409)
                row.generation += 1
                op_hash, _ = await lifecycle_digest(session, row, "skill." + action)
                approval = CapabilityApproval(id=uuid4(), tenant_id=UUID(tenant), target_id=target,
                    action="skill." + action, operation_hash=op_hash, policy_version=POLICY_VERSION,
                    expires_at=now() + timedelta(minutes=15))
                session.add(approval)
                row.approval_id, row.status = approval.id, "pending_" + action
                audit(session, tenant, target, "skill_approval_requested", action=approval.action, operation_hash=op_hash)
            await session.flush()
            return skill_dto(row)


async def apply_skill_decision(session, approval, decision):
    skill_id, version = approval.target_id.split("@")
    row = await skill_row(session, approval.tenant_id, skill_id, version)
    action = approval.action.removeprefix("skill.")
    if row.status != "pending_" + action or row.approval_id != approval.id:
        raise AppError("APPROVAL_INACTIVE", "Skill approval is no longer active", 409)
    if decision == "approved":
        digest, deps = await lifecycle_digest(session, row, approval.action)
        if digest != approval.operation_hash:
            raise AppError("APPROVAL_MISMATCH", "Skill or dependency closure changed", 409)
        if action == "install":
            row.installed_hash, row.status = row.content_hash, "installed_disabled"
        else:
            row.enabled_hash, row.status = content_hash(deps), "enabled"
        approval.status = "consumed"
    else:
        row.status = "registered" if action == "install" else "installed_disabled"
    row.generation += 1
    audit(session, approval.tenant_id, approval.target_id, "skill_" + action + "_decided", decision=decision,
          content_hash=row.content_hash)
