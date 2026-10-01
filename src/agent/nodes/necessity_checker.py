"""LangGraph node: Necessity Checker (structured module, no LLM).

Compares the extracted requirements against the capacity of the node each
service currently runs on, to decide whether a reconfiguration is required.
"""

from agent.model.schemas import NecessityCheckResult
from agent.states.state import AgentState
from agent.utils.pipeline import KPI_TO_NODE_FIELD, co_located_footprint, flow_latency_ms, to_native_unit


def necessity_checker_node(state: AgentState) -> dict:
    violated: list[str] = []
    services_to_reconsider: set[str] = set()
    current_placement = {sid: s.current_node for sid, s in state["services"].items()}

    for req in state["requirements"]:
        if req.target_type == "flow":
            flow = state["flows"].get(req.target_id)
            if flow is None or req.kpi_type != "latency":
                # Only end-to-end latency is modeled at the flow level for
                # now -- any other KPI on a flow is ignored here.
                continue
            actual_value = flow_latency_ms(flow, state["links"], current_placement, state["services"])
            target_value = req.target_value
            affected = flow.path
        else:  # target_type == "service"
            service = state["services"].get(req.target_id)
            if service is None:
                continue
            node_field = KPI_TO_NODE_FIELD.get(req.kpi_type)
            if node_field is None:
                # KPI not handled at the service level (e.g. "latency", now
                # modeled only per-flow, or any KPI not yet supported here)
                # -> ignored.
                continue
            current_node = state["nodes"][service.current_node]
            target_value = to_native_unit(req.target_value, req.unit, req.kpi_type)
            affected = [req.target_id]

            if req.comparator == "gte":
                # Floor requirement ("needs at least X available"): what
                # matters is capacity left over once other services already
                # hosted on this node have taken their share -- not the
                # node's raw total.
                total_capacity = getattr(current_node, node_field)
                actual_value = total_capacity - co_located_footprint(
                    node_field, service.current_node, req.target_id, state["services"], current_placement
                )
            else:
                # "lte"/"eq" (ceiling/exact requirements): the question is
                # whether THIS service's own usage stays within bounds, not
                # whether the node has room -- compared to the service's own
                # declared footprint, not the node's capacity.
                actual_value = (service.requirements or {}).get(node_field, 0)

        satisfied = (
            (req.comparator == "gte" and actual_value >= target_value)
            or (req.comparator == "lte" and actual_value <= target_value)
            or (req.comparator == "eq" and actual_value == target_value)
        )
        if not satisfied:
            violated.append(req.requirement_id)
            services_to_reconsider.update(affected)

    status = "reconfiguration_required" if violated else "no_action_needed"
    necessity_result = NecessityCheckResult(
        status=status,
        violated_requirements=violated,
        services_to_reconsider=sorted(services_to_reconsider),
        current_placement=current_placement,
    )
    return {"necessity_result": necessity_result}
