"""Shared state (State) of the LangGraph graph."""

from typing import TypedDict

from agent.model.schemas import (
    DecisionResult,
    Link,
    NecessityCheckResult,
    Node,
    Requirement,
    Service,
)


class AgentState(TypedDict):
    """State shared between the nodes of the LangGraph graph."""

    intent_text: str
    services: dict[str, Service]
    nodes: dict[str, Node]
    links: list[Link]
    requirements: list[Requirement]
    necessity_result: NecessityCheckResult | None
    decision_result: DecisionResult | None
    explanation: str | None
