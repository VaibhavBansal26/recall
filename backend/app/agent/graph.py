"""LangGraph agent. Phase 2: capture, then enrich (diagram + link proposals).

The router arrives with the second mode. Nodes stream their updates so the UI gets the notes
as soon as they exist, and the diagrams and links when those are ready.
"""

from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.deps import AgentDeps
from app.agent.nodes.capture import capture_node
from app.agent.nodes.enrich import enrich_node
from app.agent.state import AgentState


async def _capture(deps: AgentDeps, state: AgentState) -> dict[str, Any]:
    return (await capture_node(deps, state)).as_update()


async def _enrich(deps: AgentDeps, state: AgentState) -> dict[str, Any]:
    return (await enrich_node(deps, state)).as_update()


def build_graph(deps: AgentDeps) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("capture", partial(_capture, deps))
    graph.add_node("enrich", partial(_enrich, deps))
    graph.add_edge(START, "capture")
    graph.add_edge("capture", "enrich")
    graph.add_edge("enrich", END)
    return graph.compile()


async def stream_capture(graph: Any, state: AgentState) -> AsyncIterator[tuple[str, AgentState]]:
    """Yield (node name, state after that node) as each node finishes."""
    async for chunk in graph.astream(state, stream_mode="updates"):
        for node, update in chunk.items():
            yield node, AgentState.model_validate(update)
