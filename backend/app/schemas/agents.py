"""Model output is data, never a permission grant or executable graph definition."""
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.tools import StrictModel, SkillRef


class PlanNode(StrictModel):
    id: Literal['coder', 'researcher']
    role: Literal['coder', 'researcher']
    depends_on: list[Literal['coder', 'researcher']] = Field(default_factory=list, max_length=1)
    instruction: str = Field(min_length=1, max_length=2000)


class AgentPlan(StrictModel):
    nodes: list[PlanNode] = Field(min_length=2, max_length=2)

    @model_validator(mode='after')
    def valid_dag(self):
        if {n.id for n in self.nodes} != {'coder', 'researcher'} or any(n.id != n.role or n.id in n.depends_on for n in self.nodes):
            raise ValueError('invalid worker roles or self dependency')
        if all(n.depends_on for n in self.nodes):
            raise ValueError('cyclic dependency')
        return self


class ToolProposal(StrictModel):
    tool: Literal['notes.read', 'notes.write', 'sandbox.execute']
    arguments: dict
    skill: SkillRef | None = None


class AgentAnswer(StrictModel):
    summary: str = Field(min_length=1, max_length=16000)
    tools: list[ToolProposal] = Field(default_factory=list, max_length=3)


class AgentReview(StrictModel):
    summary: str = Field(min_length=1, max_length=16000)
    needs_revision: bool
    conflicts: list[str] = Field(default_factory=list, max_length=8)
