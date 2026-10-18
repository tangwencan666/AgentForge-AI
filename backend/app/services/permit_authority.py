"""In-process sealed authorities. Public identifiers do not confer authority."""
import hashlib
import secrets
from dataclasses import dataclass, field
from uuid import UUID
from app.core.errors import AppError
from app.providers.base import ProviderFailure

_SEAL = object()


@dataclass(frozen=True, repr=False)
class IssuerAuthority:
    tenant_id: str
    _seal: object = field(repr=False)


def verify_issuer(token, settings):
    expected = settings.model_permit_issuer_token
    if not expected or not token or not secrets.compare_digest(token.encode(), expected.get_secret_value().encode()):
        raise AppError('PERMIT_ISSUER_FORBIDDEN', 'Independent permit issuer authority required', 403)
    return IssuerAuthority(settings.tenant_id, _SEAL)


def require_issuer(authority, settings):
    if type(authority) is not IssuerAuthority or authority._seal is not _SEAL or authority.tenant_id != settings.tenant_id:
        raise AppError('PERMIT_ISSUER_FORBIDDEN', 'Trusted issuer authority required', 403)


@dataclass(frozen=True, repr=False)
class WorkerIdentity:
    identity: UUID
    owner: str
    _proof: str = field(repr=False)
    _seal: object = field(repr=False)

    def proof_hash(self):
        if self._seal is not _SEAL:
            raise AppError('PERMIT_WORKER_FORBIDDEN', 'Trusted worker identity required', 403)
        return hashlib.sha256(self._proof.encode()).hexdigest()


def mint_worker_identity(identity, owner):
    # Only the trusted local Worker bootstrap calls this; there is no registration HTTP route.
    return WorkerIdentity(identity, owner, secrets.token_hex(32), _SEAL)


@dataclass(repr=False)
class DispatchLease:
    service: object = field(repr=False)
    permit_id: UUID
    identity: WorkerIdentity = field(repr=False)
    fence: int
    _seal: object = field(repr=False)

    async def commit(self, config, body):
        return await self.service.commit_dispatch(self, config, body)


def mint_dispatch_lease(service, permit_id, identity, fence):
    return DispatchLease(service, permit_id, identity, fence, _SEAL)


def require_dispatch(lease):
    if type(lease) is not DispatchLease or getattr(lease, '_seal', None) is not _SEAL:
        raise ProviderFailure('MODEL_PERMIT_REQUIRED')
    return lease


def reject_unpermitted_real():
    raise AppError('MODEL_PERMIT_REQUIRED', 'Real execution requires an independently issued single-use permit', 409)


def require_permit_task(task):
    if task.options.get('workflow') != 'permit_test' or not task.options.get('permit_id'):
        reject_unpermitted_real()
