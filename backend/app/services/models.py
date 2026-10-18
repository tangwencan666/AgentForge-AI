import os
from uuid import UUID
from sqlalchemy import select, update
from app.core.config import Settings, validate_model_endpoint
from app.core.errors import AppError
from app.domain.entities import ModelSlot
from app.schemas.models import ModelConfig, ModelRole, ModelUpdate
from app.services.context import redact


def validate_configuration(config: ModelConfig, settings: Settings) -> None:
    serialized = config.model_dump_json(exclude={"expected_version"})
    if redact(serialized,settings) != serialized:
        raise AppError("CONFIGURATION_CONTAINS_SECRET", "Use protected references instead of secret values", 422)
    if config.base_url:
        try:
            validate_model_endpoint(config.base_url, settings.model_hosts)
        except ValueError:
            raise AppError("INVALID_MODEL_ENDPOINT", "Model endpoint is not approved", 422) from None
    if config.enabled and config.provider != "mock":
        from app.providers.router import resolve_credential
        resolve_credential(config.credential_reference, settings)


def slot_dto(slot: ModelSlot) -> dict:
    config = {name: getattr(slot, name) for name in ModelConfig.model_fields}
    return {
        "role": slot.role, **config, "version": slot.version,
        "is_mock": slot.provider == "mock", "call_status": "mock" if slot.provider == 'mock' else 'not_tested',
        "credential_configured": credential_configured(slot.credential_reference),
    }


def credential_configured(ref):
    from dotenv import dotenv_values
    from app.core.config import runtime_env_file
    name = (ref or '').removeprefix('env:')
    if not ref:
        return False
    if name in os.environ:
        return True  # Presence only; do not read or authenticate the value.
    if os.environ.get('AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY', 'true').lower() in {'1', 'true'}:
        return False
    return name in dotenv_values(runtime_env_file())


async def list_slots(session, tenant_id: str) -> list[dict]:
    rows = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == UUID(tenant_id)))).all()
    by_role = {row.role: row for row in rows}
    if set(by_role) != {role.value for role in ModelRole}:
        raise AppError("MODEL_SLOTS_NOT_INITIALIZED", "Run project database migration", 503)
    from app.domain.tasks import ModelOperation, AgentTask
    result = []
    for role in ModelRole:
        dto = slot_dto(by_role[role.value])
        last = await session.scalar(select(ModelOperation).join(AgentTask).where(AgentTask.tenant_id == UUID(tenant_id),
            ModelOperation.role == role.value, ModelOperation.is_mock.is_(False),
            AgentTask.model_snapshot[role.value]['config_version'].astext == str(by_role[role.value].version)).order_by(ModelOperation.started_at.desc()).limit(1))
        dto['call_status'] = last.error_code or last.state if last else ('mock' if dto['is_mock'] else 'not_tested')
        result.append(dto)
    return result


async def update_slot(session, tenant_id: str, role: ModelRole, config: ModelUpdate, settings: Settings) -> dict:
    validate_configuration(config, settings)
    values = config.model_dump(exclude={"expected_version"})
    statement = update(ModelSlot).where(
        ModelSlot.tenant_id == UUID(tenant_id), ModelSlot.role == role.value,
        ModelSlot.version == config.expected_version,
    ).values(**values, version=ModelSlot.version + 1).returning(ModelSlot)
    row = (await session.scalars(statement)).one_or_none()
    if row is None:
        raise AppError("CONFIGURATION_CONFLICT", "Configuration version changed or slot unavailable", 409)
    dto = slot_dto(row)
    await session.commit()
    return dto
