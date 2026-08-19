"""Assembly of the StateGraph matching the architecture diagram.

User Input -> Intent Grounding -> Necessity Checker --Yes--> Decision Engine -\\
                                                    \\--No----------------------> Trace & Explanation Generation -> User Input
"""

from langgraph.graph import END, StateGraph

from agent.nodes.decision_engine import decision_engine_node
from agent.nodes.explanation import explanation_node
from agent.nodes.intent_grounding import intent_grounding_node
from agent.nodes.necessity_checker import necessity_checker_node
from agent.states.state import AgentState


def _route_after_necessity_check(state: AgentState) -> str:
    if state["necessity_result"].status == "reconfiguration_required":
        return "decision_engine"
    return "explanation"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("intent_grounding", intent_grounding_node)
    graph.add_node("necessity_checker", necessity_checker_node)
    graph.add_node("decision_engine", decision_engine_node)
    graph.add_node("explanation", explanation_node)

    graph.set_entry_point("intent_grounding")
    graph.add_edge("intent_grounding", "necessity_checker")
    graph.add_conditional_edges(
        "necessity_checker",
        _route_after_necessity_check,
        {"decision_engine": "decision_engine", "explanation": "explanation"},
    )
    graph.add_edge("decision_engine", "explanation")
    graph.add_edge("explanation", END)

    return graph.compile()
