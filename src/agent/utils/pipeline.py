"""Shared helpers for reasoning over the application's pipeline.

The pipeline is a DAG defined by Service.next_services, laid over the
physical nodes/links infrastructure. Used by both necessity_checker.py
(checking the current placement) and decision_engine.py (the CSP model,
checking candidate placements).
"""

from agent.model.schemas import Link, Service


def build_predecessor_map(services: dict[str, Service]) -> dict[str, str]:
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


def chain_to(service_id: str, predecessors: dict[str, str]) -> list[str]:
    """Ordered list of service_ids from the pipeline's root down to (and
    including) service_id."""
    chain = [service_id]
    current = service_id
    while current in predecessors:
        current = predecessors[current]
        chain.append(current)
    chain.reverse()
    return chain


def find_link(node_a: str, node_b: str, links: list[Link]) -> Link | None:
    for link in links:
        if {link.source_node, link.target_node} == {node_a, node_b}:
            return link
    return None


def cumulative_latency_ms(
    service_id: str,
    services: dict[str, Service],
    links: list[Link],
    node_by_service: dict[str, str],
) -> float:
    """Cumulative network latency from the pipeline's root down to
    service_id (inclusive of every hop along the way), following
    next_services edges.

    node_by_service maps each service_id to the node it's hosted on --
    pass {sid: s.current_node for sid, s in services.items()} to evaluate the
    real, current placement, or a candidate/hypothetical placement (e.g. from
    the decision engine's search) to evaluate a placement being considered.

    Assumes consecutive services in the pipeline are hosted on the same node
    (0ms hop) or on two directly linked nodes -- multi-hop routing is not
    supported yet, see README "Known limitations".
    """
    chain = chain_to(service_id, build_predecessor_map(services))

    total_ms = 0.0
    for upstream_id, downstream_id in zip(chain, chain[1:]):
        node_a = node_by_service[upstream_id]
        node_b = node_by_service[downstream_id]
        if node_a == node_b:
            continue  # co-located, no network hop

        link = find_link(node_a, node_b, links)
        if link is None:
            raise ValueError(
                f"No direct link between {node_a!r} and {node_b!r} "
                f"(consecutive services {upstream_id!r} -> {downstream_id!r}) -- "
                "multi-hop routing is not supported yet."
            )
        total_ms += link.latency_ms

    return total_ms
