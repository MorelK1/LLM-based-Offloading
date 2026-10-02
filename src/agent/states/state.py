"""Shared state (State) of the LangGraph graph."""

from typing import TypedDict

from agent.model.schemas import (
    DecisionResult,
    Flow,
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
    flows: dict[str, Flow]
    nodes: dict[str, Node]
    links: list[Link]
    requirements: list[Requirement]
    necessity_result: NecessityCheckResult | None
    decision_result: DecisionResult | None
    explanation: str | None
    # Telemetry for the two LLM calls -- populated by intent_grounding_node/
    # explanation_node, read by nobody in the real pipeline today. Exists so
    # experimentation scripts can later compare models/strategies on time and
    # cost, not just correctness, without having to re-run anything once
    # it's captured. usage is LangChain's UsageMetadata dict (input_tokens/
    # output_tokens/total_tokens) when the provider returns it, else None.
    # The actual resolved model name for each call, even when the node's
    # `model` param is None (.env's OPENROUTER_MODEL fallback) -- without
    # this, a record built from a None-override run can't say which model
    # actually ran it.
    extraction_model: str | None
    extraction_elapsed_s: float | None
    extraction_token_usage: dict | None
    extraction_parsing_error: str | None
    explanation_model: str | None
    explanation_elapsed_s: float | None
    explanation_token_usage: dict | None
