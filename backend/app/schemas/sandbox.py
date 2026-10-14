"""P3 public and trusted execution contracts; no Docker policy overrides."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

POLICY_VERSION = "p3-python-v2"

class ResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    cpu: Literal[0.25, 0.5, 1.0] = 0.5
    memory_mb: int = Field(default=128, ge=64, le=512, strict=True)
    pids: int = Field(default=32, ge=8, le=64, strict=True)

    @field_validator("cpu",mode="before")
    @classmethod
    def numeric_cpu(cls,value):
        if isinstance(value,bool): raise ValueError("CPU must be an approved numeric quota")
        return value

class SandboxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    language: Literal["python"] = "python"
    code: SecretStr = Field(min_length=1, max_length=65536, repr=False)
    timeout_seconds: int = Field(default=30, ge=1, le=120, strict=True)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)

class SandboxExecutionRequest(SandboxCreate):
    task_id: UUID
    execution_id: UUID
    approval_reference: UUID

class RunnerDispatch(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    task_id: UUID
    execution_id: UUID
    owner: str = Field(min_length=1, max_length=64)
    fence: int = Field(ge=1, strict=True)

class SandboxExecutionResult(BaseModel):
    execution_id: UUID
    status: str
    exit_code: int | None = None
    stdout_summary: str = ""
    stderr_summary: str = ""
    duration_ms: int | None = None
    resource_usage: dict = Field(default_factory=dict)
    container_id: str | None = None
    failure_reason: str | None = None
    cleanup_status: str
