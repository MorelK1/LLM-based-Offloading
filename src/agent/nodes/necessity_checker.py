"""LangGraph node: Necessity Checker (structured module, no LLM).

Compares the extracted requirements against the capacity of the node each
service currently runs on, to decide whether a reconfiguration is required.
"""

from agent.model.schemas import Link, NecessityCheckResult, Service
from agent.states.state import AgentState

_KPI_TO_NODE_FIELD = {
    "cpu": "cpu_cores",
    "ram": "ram_gb",
}


def _build_predecessor_map(services: dict[str, Service]) -> dict[str, str]:
    """Reverse next_services edges into a {service_id: predecessor_id} map.

    A service with more than one predecessor (a merge point in the pipeline
    DAG) is not supported yet -- see README "Known limitations".
    """
    predecessors: dict[str, str] = {}
    for service in services.values():
        for next_id in service.next_services:
            if next_id in predecessors:
                raise ValueError(
                    f"Service {next_id!r} has more than one predecessor "
                    f"({predecessors[next_id]!r} and {service.service_id!r}) -- "
                    "merge points in the pipeline are not supported yet."
                )
            predecessors[next_id] = service.service_id
    return predecessors


def _find_link(node_a: str, node_b: str, links: list[Link]) -> Link | None:
    for link in links:
        if {link.source_node, link.target_node} == {node_a, node_b}:
            return link
    return None


def _cumulative_latency_ms(
    service_id: str,
    services: dict[str, Service],
    links: list[Link],
) -> float:
    """Cumulative network latency from the pipeline's root down to service_id
    (inclusive of every hop along the way), following next_services edges.

    Assumes consecutive services in the pipeline are hosted on the same node
    (0ms hop) or on two directly linked nodes -- multi-hop routing is not
    supported yet, see README "Known limitations".
    """
    predecessors = _build_predecessor_map(services)

    chain = [service_id]
    current = service_id
    while current in predecessors:
        current = predecessors[current]
        chain.append(current)
    chain.reverse()  # root -> service_id

    total_ms = 0.0
    for upstream_id, downstream_id in zip(chain, chain[1:]):
        node_a = services[upstream_id].current_node
        node_b = services[downstream_id].current_node
        if node_a == node_b:
            continue  # co-located, no network hop

        link = _find_link(node_a, node_b, links)
        if link is None:
            raise ValueError(
                f"No direct link between {node_a!r} and {node_b!r} "
                f"(consecutive services {upstream_id!r} -> {downstream_id!r}) -- "
                "multi-hop routing is not supported yet."
            )
        total_ms += link.latency_ms

    return total_ms


def necessity_checker_node(state: AgentState) -> dict:
    violated: list[str] = []
    services_to_reconsider: set[str] = set()

    for req in state["requirements"]:
        service = state["services"].get(req.service)
        if service is None:
            continue

        if req.kpi_type == "latency":
            # Cumulative end-to-end latency from the pipeline's start up to
            # (and including) this service -- not a per-node capacity.
            actual_value = _cumulative_latency_ms(
                req.service, state["services"], state["links"]
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
