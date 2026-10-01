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


def _to_native_unit(value: float, unit: str, kpi_type: str) -> float:
    """Converts a requirement's target_value into the unit of Node's matching
    field (cpu_cores: vCPU, ram_gb: GB) -- e.g. a 20 MB target must become 0.02
    before being compared to a node's ram_gb (an int, in GB, never MB)."""
    if kpi_type == "ram" and unit == "MB":
        return value / 1024
    return value


def _co_located_footprint(node_field: str, current_node_id: str, exclude_service_id: str, services: dict) -> float:
    """Sums the static footprint (Service.requirements[node_field]) of every
    other service already placed on current_node_id -- services without a
    declared footprint contribute 0, not an unknown/error."""
    return sum(
        (other.requirements or {}).get(node_field, 0)
        for other_id, other in services.items()
        if other_id != exclude_service_id and other.current_node == current_node_id
    )


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
            target_value = req.target_value
        else:
            node_field = _KPI_TO_NODE_FIELD.get(req.kpi_type)
            if node_field is None:
                # KPI not handled by this module -> ignored here.
                continue
            current_node = state["nodes"][service.current_node]
            total_capacity = getattr(current_node, node_field)

            if req.comparator == "gte":
                # Floor requirement ("needs at least X available"): what
                # matters is capacity left over once other services already
                # hosted on this node have taken their share -- not the
                # node's raw total.
                actual_value = total_capacity - _co_located_footprint(
                    node_field, service.current_node, req.service, state["services"]
                )
                target_value = _to_native_unit(req.target_value, req.unit, req.kpi_type)
            else:
                # "lte"/"eq" (ceiling/exact requirements) are left on the
                # pre-existing raw-capacity comparison for this version --
                # see data/enact_scenario/RESULTS.md / experimentation/
                # METHODOLOGY.md for why a ceiling needs a per-service usage
                # comparison instead, deferred to a later revision.
                actual_value = total_capacity
                target_value = req.target_value

        satisfied = (
            (req.comparator == "gte" and actual_value >= target_value)
            or (req.comparator == "lte" and actual_value <= target_value)
            or (req.comparator == "eq" and actual_value == target_value)
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
