"""LangGraph node: Necessity Checker (structured module, no LLM).

Compares the extracted requirements against the capacity of the node each
service currently runs on, to decide whether a reconfiguration is required.
"""

from agent.model.schemas import NecessityCheckResult
from agent.states.state import AgentState
from agent.utils.pipeline import cumulative_latency_ms

_KPI_TO_NODE_FIELD = {
    "cpu": "cpu_cores",
    "ram": "ram_gb",
}


def necessity_checker_node(state: AgentState) -> dict:
    violated: list[str] = []
    services_to_reconsider: set[str] = set()
    current_placement = {sid: s.current_node for sid, s in state["services"].items()}

    for req in state["requirements"]:
        service = state["services"].get(req.service)
        if service is None:
            continue

        if req.kpi_type == "latency":
            # Cumulative end-to-end latency from the pipeline's start up to
            # (and including) this service -- not a per-node capacity.
            actual_value = cumulative_latency_ms(
                req.service, state["services"], state["links"], current_placement
            )
        else:
            node_field = _KPI_TO_NODE_FIELD.get(req.kpi_type)
            if node_field is None:
                # KPI not handled by this module -> ignored here.
                continue
            current_node = state["nodes"][service.current_node]
            actual_value = getattr(current_node, node_field)

        satisfied = (
            (req.comparator == "gte" and actual_value >= req.target_value)
            or (req.comparator == "lte" and actual_value <= req.target_value)
            or (req.comparator == "eq" and actual_value == req.target_value)
        )
        if not satisfied:
            violated.append(req.requirement_id)
            services_to_reconsider.add(req.service)

    status = "reconfiguration_required" if violated else "no_action_needed"
    necessity_result = NecessityCheckResult(
        status=status,
        violated_requirements=violated,
        services_to_reconsider=sorted(services_to_reconsider),
    )
    return {"necessity_result": necessity_result}
