import secrets
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import Depends
from app.core.errors import AppError

bearer = HTTPBearer(auto_error=False)


def require_admin(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    expected = request.app.state.settings.admin_token.get_secret_value()
    if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise AppError("UNAUTHORIZED", "Authentication required", 401)
    # P1 single local admin. Tenant identity is server-controlled, never a client header.
    return request.app.state.settings.tenant_id
