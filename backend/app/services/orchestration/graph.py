from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from app.core.errors import AppError
from app.services.context import content_hash


class GraphState(TypedDict, total=False):
    task_id: str
    plan: dict
    plan_hash: str
    round: int
    coder: str
    researcher: str
    review: str
    needs_revision: bool


def validate_plan(plan):
    nodes = plan.get("nodes", [])
    if len(nodes) != 2 or {n.get("id") for n in nodes} != {"coder", "researcher"}:
        raise AppError("INVALID_PLAN", "Unsupported worker plan", 422)
    graph = {n["id"]: n.get("depends_on", []) for n in nodes}
    if any(n.get("role") != n["id"] or n.get("tools", []) for n in nodes):
        raise AppError("INVALID_PLAN", "Plan cannot grant tools or replace roles", 422)
    def visit(node, path):
        if node in path or node not in graph:
            raise AppError("INVALID_PLAN", "Cyclic or invalid dependency", 422)
        for dep in graph[node]:
            visit(dep, path | {node})
    for node in graph:
        visit(node, set())
    return graph


def build_graph(runtime, saver):
    async def planner(state):
        options = await runtime.options()
        mode = options["worker_dependency"]
        plan = {"nodes":[{"id":"coder","role":"coder","depends_on":["researcher"] if mode == "research_first" else [],"tools":[]},
                         {"id":"researcher","role":"researcher","depends_on":["coder"] if mode == "code_first" else [],"tools":[]}],"is_mock":True}
        result = await runtime.operation("planner", 0, {"plan":plan,"summary":"[MOCK] Deterministic two-worker plan"})
        validate_plan(result["plan"])
        digest = await runtime.record_plan(result["plan"])
        return {"plan":result["plan"],"plan_hash":digest,"round":0}

    async def approve(state):
        status = await runtime.approval_state(state["plan_hash"])
        if status != "approved":
            interrupt({"type":"plan_confirmation","plan_hash":state["plan_hash"],"is_mock":True})
            # Resume payload is only a wake-up; authoritative decision is read again.
            if await runtime.approval_state(state["plan_hash"]) != "approved":
                raise AppError("APPROVAL_REQUIRED", "Approval has not been granted", 403)
        return {}

    async def dispatch(state):
        await runtime.begin_round(state["round"])
        return {}

    def route_workers(state):
        dependencies = validate_plan(state["plan"])
        if dependencies["coder"]:
            return "research_first"
        if dependencies["researcher"]:
            return "code_first"
        return ["coder_parallel", "researcher_parallel"]

    async def coder(state):
        result = await runtime.operation("coder", state["round"], {"summary":"[MOCK] Coder draft; no code was executed"})
        return {"coder":result["operation_id"]}

    async def researcher(state):
        result = await runtime.operation("researcher", state["round"], {"summary":"[MOCK] Research outline; no external research was performed"})
        return {"researcher":result["operation_id"]}

    async def review(state):
        options = await runtime.options()
        revise = state["round"] < options["mock_options"]["review_rounds"]
        result = await runtime.operation("reviewer", state["round"], {"summary":"[MOCK] Reviewer feedback; not a permission grant", "needs_revision":revise})
        return {"review":result["operation_id"],"needs_revision":revise}

    async def increment(state):
        return {"round":state["round"] + 1}

    builder = StateGraph(GraphState)
    for name, fn in [("planner",planner),("approval",approve),("dispatch",dispatch),("coder_parallel",coder),
                     ("researcher_parallel",researcher),("research_first",researcher),("code_after_research",coder),
                     ("code_first",coder),("research_after_code",researcher),("reviewer",review),("increment",increment)]:
        builder.add_node(name, fn)
    builder.add_edge(START,"planner")
    builder.add_edge("planner","approval")
    builder.add_edge("approval","dispatch")
    builder.add_conditional_edges("dispatch",route_workers)
    builder.add_edge(["coder_parallel","researcher_parallel"],"reviewer")
    builder.add_edge("research_first","code_after_research")
    builder.add_edge("code_after_research","reviewer")
    builder.add_edge("code_first","research_after_code")
    builder.add_edge("research_after_code","reviewer")
    builder.add_conditional_edges("reviewer",lambda state:"increment" if state["needs_revision"] else END)
    builder.add_edge("increment","dispatch")
    return builder.compile(checkpointer=saver)
