"""Only curated tool schemas and data-only Skill manifests are accepted."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

POLICY_VERSION = "p4-gateway-v1"
PROTOCOL_VERSION = "2025-11-25"
AUDIENCE = "agentforge-controlled-mcp/v1"
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,47}$")]
Version = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ToolName = Literal["notes.read", "notes.write"]
Permission = Literal["notes:read", "notes:write"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ReadNote(StrictModel):
    resource: Slug


class WriteNote(ReadNote):
    text: str = Field(min_length=1, max_length=4096)


class NoteResult(StrictModel):
    resource: Slug
    text: str = Field(max_length=4096)
    revision: int = Field(ge=0)
    found: bool


class SkillRef(StrictModel):
    skill_id: Slug
    version: Version


class ToolRequest(StrictModel):
    tool: ToolName
    arguments: dict
    skill: SkillRef | None = None


class PermissionUpdate(StrictModel):
    tool: ToolName
    resource: Slug
    allowed: bool


class Dependency(SkillRef):
    content_hash: Digest


class SkillManifest(StrictModel):
    skill_id: Slug
    version: Version
    description: str = Field(min_length=1, max_length=512)
    instructions: str = Field(min_length=1, max_length=8192)
    tools: list[ToolName] = Field(min_length=1, max_length=2)
    required_permissions: list[Permission] = Field(min_length=1, max_length=2)
    dependencies: list[Dependency] = Field(default_factory=list, max_length=8)
    compatibility: Literal["p4-declarative-v1"] = "p4-declarative-v1"

    @field_validator("tools", "required_permissions", "dependencies")
    @classmethod
    def unique_items(cls, values):
        import json
        keys = [json.dumps(v.model_dump() if isinstance(v, BaseModel) else v, sort_keys=True) for v in values]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate manifest entries")
        return values


class SkillCandidate(StrictModel):
    manifest: SkillManifest
    source: Literal["human", "agent"] = "human"


class SkillAction(StrictModel):
    action: Literal["register", "install", "enable", "disable", "revoke"]


class CapabilityDecision(StrictModel):
    decision: Literal["approved", "rejected"]
    operation_hash: Digest


CATALOG = {
    "notes.read": {"name": "notes.read", "version": "1.0.0", "permission": "notes:read", "high_risk": False,
                   "description": "Read one tenant-owned managed note", "input": ReadNote},
    "notes.write": {"name": "notes.write", "version": "1.0.0", "permission": "notes:write", "high_risk": True,
                    "description": "Write one tenant-owned managed note (independent approval required)", "input": WriteNote},
}


def public_catalog():
    return [{"name": v["name"], "version": v["version"], "description": v["description"],
             "permission": v["permission"], "high_risk": v["high_risk"], "inputSchema": v["input"].model_json_schema(),
             "outputSchema": NoteResult.model_json_schema(), "timeout_seconds": 8, "server": "controlled-stdio-v1"}
            for v in CATALOG.values()]
