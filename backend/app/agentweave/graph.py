"""L4 LangGraph definition; the approval node has no pre-interrupt side effects."""

from collections.abc import Callable
from typing import Any, cast

from app.agentweave.state import WorkflowState

WorkflowNode = Callable[[WorkflowState], dict[str, Any]]


def build_graph(nodes: dict[str, WorkflowNode], *, checkpointer: Any) -> Any:
    """Compile a graph from deterministic handlers and a required checkpointer."""
    required_nodes = {"diagnose", "work_order", "parts", "schedule", "partial_hitl", "finalize"}
    missing = required_nodes - nodes.keys()
    if missing:
        raise ValueError(f"Missing workflow node handlers: {', '.join(sorted(missing))}")
    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt
    except ImportError as error:
        raise RuntimeError("LangGraph is required to build the resumable workflow") from error

    def hitl_gate(state: WorkflowState) -> dict[str, Any]:
        decision = interrupt(state["approval_package"])
        return {"approval": decision}

    def after_diagnosis(state: WorkflowState) -> str:
        return "partial_hitl" if state.get("status") == "partial" else "work_order"

    def after_finalize(state: WorkflowState) -> str:
        approval = state.get("approval", {})
        return "hitl_gate" if approval.get("decision") == "escalate" else END

    builder = StateGraph(WorkflowState)
    for name in ("diagnose", "work_order", "parts", "schedule", "partial_hitl", "finalize"):
        builder.add_node(name, cast(Any, nodes[name]))
    builder.add_node("hitl_gate", hitl_gate)
    builder.add_edge(START, "diagnose")
    builder.add_conditional_edges(
        "diagnose",
        after_diagnosis,
        {"partial_hitl": "partial_hitl", "work_order": "work_order"},
    )
    builder.add_edge("work_order", "parts")
    builder.add_edge("parts", "schedule")
    builder.add_edge("schedule", "hitl_gate")
    builder.add_edge("partial_hitl", "hitl_gate")
    builder.add_edge("hitl_gate", "finalize")
    builder.add_conditional_edges("finalize", after_finalize)
    return builder.compile(checkpointer=checkpointer)
