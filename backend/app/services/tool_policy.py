from dataclasses import dataclass
from app.core.errors import AppError


@dataclass(frozen=True)
class ToolGrant:
    tool: str
    allowed: bool
    high_risk: bool
    approval_valid: bool = False
    requester: str = "local-admin"
    approver: str | None = None


def authorize_tool(grant: ToolGrant, agent_role: str) -> None:
    """Trusted server policy inputs only. No tool execution is provided in P2."""
    if agent_role == "reviewer" or not grant.allowed:
        raise AppError("TOOL_FORBIDDEN", "Tool permission is required", 403)
    if grant.high_risk and (not grant.approval_valid or grant.approver == grant.requester or not grant.approver):
        raise AppError("TOOL_APPROVAL_REQUIRED", "Independent valid approval is required", 403)
    if grant.tool in {"sandbox.execute", "mcp.call", "skills.execute"}:
        raise AppError("TOOL_UNAVAILABLE", "This execution capability is not implemented", 503)
