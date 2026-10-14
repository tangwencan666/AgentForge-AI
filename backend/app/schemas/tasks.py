from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class MockOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latency_ms: int = Field(default=100, ge=0, le=2000, strict=True)
    fail_role: Literal["planner", "coder", "researcher", "reviewer"] | None = None
    review_rounds: int = Field(default=0, ge=0, le=8, strict=True)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    goal: str = Field(min_length=1, max_length=12000)
    execution_mode: Literal["mock"]
    worker_dependency: Literal["independent", "research_first", "code_first"] = "independent"
    require_approval: bool = True
    timeout_seconds: int = Field(default=900, ge=1, le=900, strict=True)
    max_iterations: int = Field(default=8, ge=1, le=8, strict=True)
    max_calls: int = Field(default=32, ge=1, le=32, strict=True)
    max_tokens: int = Field(default=100000, ge=1, le=100000, strict=True)
    max_budget_usd: Decimal = Field(default=Decimal("1"), gt=0, le=1, max_digits=9, decimal_places=8, allow_inf_nan=False)
    mock_options: MockOptions = Field(default_factory=MockOptions)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    operation_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
