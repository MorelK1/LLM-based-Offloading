"""LangGraph node: Decision Engine (solver, structured module).

v0: greedy search for the "cheapest" node (lowest tier) that satisfies all
requirements of the service. TODO: replace with a proper constraint solver
(e.g. OR-Tools) accounting for multi-service end-to-end latency and network
links.
"""

from agent.model.schemas import DecisionResult, Node, Requirement
from agent.states.state import AgentState

_TIER_ORDER = {"iot": 0, "edge": 1, "fog": 2, "cloud": 3}
_KPI_TO_NODE_FIELD = {
    "cpu": "cpu_cores",
    "ram": "ram_gb",
}


def _node_satisfies(node: Node, service_requirements: list[Requirement]) -> bool:
    for req in service_requirements:
        node_field = _KPI_TO_NODE_FIELD.get(req.kpi_type)
        if node_field is None:
            continue
        value = getattr(node, node_field)
        if req.comparator == "gte" and value < req.target_value:
            return False
        if req.comparator == "lte" and value > req.target_value:
            return False
        if req.comparator == "eq" and value != req.target_value:
            return False
    return True


def decision_engine_node(state: AgentState) -> dict:
    necessity_result = state["necessity_result"]
    requirements = state["requirements"]
    services = state["services"]
    nodes = state["nodes"]

    decision: dict[str, str] = {}
    eligible_nodes_considered: list[str] = []
    requirements_satisfied: list[str] = []

    for service_id in necessity_result.services_to_reconsider:
        service_requirements = [r for r in requirements if r.service == service_id]

        candidates = sorted(nodes.values(), key=lambda n: _TIER_ORDER[n.tier])
        eligible_nodes_considered.extend(n.node_id for n in candidates)

        chosen = next((n for n in candidates if _node_satisfies(n, service_requirements)), None)
        if chosen is None:
            raise ValueError(
                f"No node in the infrastructure satisfies the requirements of service {service_id}"
            )

        decision[service_id] = chosen.node_id
        requirements_satisfied.extend(r.requirement_id for r in service_requirements)

    new_configuration = {sid: s.current_node for sid, s in services.items()}
    new_configuration.update(decision)

    decision_result = DecisionResult(
        decision=decision,
        eligible_nodes_considered=sorted(set(eligible_nodes_considered)),
        requirements_satisfied=requirements_satisfied,
        new_configuration=new_configuration,
    )
    return {"decision_result": decision_result}
