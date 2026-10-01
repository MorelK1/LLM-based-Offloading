"""Shared helpers for reasoning over the application's pipeline.

The pipeline is the set of Flows (each an ordered chain of service_ids, see
schemas.py:Flow), laid over the physical nodes/links infrastructure. Several
flows may share services at their endpoints -- each flow is independently a
simple path, so there is no global merge-point restriction to enforce here.
Used by both necessity_checker.py (checking the current placement) and
decision_engine.py (the CSP model, checking candidate placements).
"""

import math

from agent.model.schemas import Flow, Link, Node, Requirement, Service

KPI_TO_NODE_FIELD = {
    "cpu": "cpu_cores",
    "ram": "ram_gb",
}
NODE_FIELD_TO_KPI = {v: k for k, v in KPI_TO_NODE_FIELD.items()}


def flow_pairs(flow: Flow) -> list[tuple[str, str]]:
    """Consecutive (upstream, downstream) service_id pairs along flow.path."""
    return list(zip(flow.path, flow.path[1:]))


def all_flow_pairs(flows: list[Flow]) -> set[tuple[str, str]]:
    """Every consecutive pair across every flow, deduplicated -- several
    flows can share the same hop (e.g. both starting at the same service)."""
    pairs: set[tuple[str, str]] = set()
    for flow in flows:
        pairs.update(flow_pairs(flow))
    return pairs


def to_native_unit(value: float, unit: str, kpi_type: str) -> float:
    """Converts a requirement's target_value into the unit of Node's matching
    field (cpu_cores: vCPU, ram_gb: GB) -- e.g. a 20 MB target must become 0.02
    before being compared to a node's ram_gb (an int, in GB, never MB)."""
    if kpi_type == "ram" and unit == "MB":
        return value / 1024
    return value


def co_located_footprint(
    node_field: str,
    node_id: str,
    exclude_service_id: str,
    services: dict[str, Service],
    node_by_service: dict[str, str],
) -> float:
    """Sums the static footprint (Service.requirements[node_field]) of every
    other service placed on node_id according to node_by_service -- pass
    {sid: s.current_node for sid, s in services.items()} to evaluate the real
    placement, or a candidate placement to evaluate one being considered.
    Services without a declared footprint contribute 0, not an unknown/error.
    """
    return sum(
        (other.requirements or {}).get(node_field, 0)
        for other_id, other in services.items()
        if other_id != exclude_service_id and node_by_service.get(other_id) == node_id
    )


def find_link(node_a: str, node_b: str, links: list[Link]) -> Link | None:
    for link in links:
        if {link.source_node, link.target_node} == {node_a, node_b}:
            return link
    return None


def flow_latency_ms(
    flow: Flow,
    links: list[Link],
    node_by_service: dict[str, str],
    services: dict[str, Service],
) -> float:
    """Total end-to-end delay for the whole flow: processing_delay (sum of
    each service's wcet_ms along flow.path, 0 if undeclared -- additive, no
    behavior change for services that don't set it) + communication_delay
    (sum of per-hop network delay, 0 for a co-located hop).

    Per-hop communication delay uses one of two models, chosen per hop based
    on whether the UPSTREAM service declares output_size: if it does, the
    hop is costed as ceil(output_size / link.bandwidth_mbps) (a data-size-
    aware transmission-time model); otherwise it falls back to the link's
    static latency_ms (the original model, still what the toy example and
    ENACT scenario use, since neither declares output_size).

    node_by_service maps each service_id to the node it's hosted on --
    pass {sid: s.current_node for sid, s in services.items()} to evaluate the
    real, current placement, or a candidate/hypothetical placement (e.g. from
    the decision engine's search) to evaluate a placement being considered.

    Assumes consecutive services in the flow are hosted on the same node
    (0ms hop) or on two directly linked nodes -- multi-hop routing is not
    supported yet, see README "Known limitations".
    """
    processing_delay = sum(
        (services[sid].wcet_ms or 0.0) for sid in flow.path if sid in services
    )

    communication_delay = 0.0
    for upstream_id, downstream_id in flow_pairs(flow):
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

        upstream_service = services.get(upstream_id)
        if upstream_service is not None and upstream_service.output_size is not None:
            communication_delay += math.ceil(upstream_service.output_size / link.bandwidth_mbps)
        else:
            communication_delay += link.latency_ms

    return processing_delay + communication_delay


def effective_service_capacity(
    service_id: str,
    node_field: str,
    services: dict[str, Service],
    active_requirements: list[Requirement],
) -> float:
    """What service_id should count for toward node_field's capacity sum:
    an active requirement's target_value (converted to node_field's native
    unit) if one targets this exact (service, kpi) -- regardless of
    comparator, since any active requirement replaces the service's
    effective footprint going forward, not just a 'gte' one (mirrors how
    public_safety's benchmark defines "baseline requirement is replaced").
    Otherwise falls back to the static baseline (Service.requirements)."""
    kpi_type = NODE_FIELD_TO_KPI[node_field]
    for req in active_requirements:
        if req.target_type == "service" and req.target_id == service_id and req.kpi_type == kpi_type:
            return to_native_unit(req.target_value, req.unit, req.kpi_type)
    return (services[service_id].requirements or {}).get(node_field, 0)


def effective_flow_latency_target(
    flow_id: str,
    flows: dict[str, Flow],
    active_requirements: list[Requirement],
) -> float | None:
    """The latency budget flow_id must respect: an active requirement's
    target_value if one targets this flow, else its static baseline
    (Flow.requirements["latency"]), else None (no constraint at all)."""
    for req in active_requirements:
        if req.target_type == "flow" and req.target_id == flow_id and req.kpi_type == "latency":
            return req.target_value
    return (flows[flow_id].requirements or {}).get("latency")


def capacity_satisfied(
    nodes: dict[str, Node],
    services: dict[str, Service],
    active_requirements: list[Requirement],
    node_by_service: dict[str, str],
) -> list[tuple[bool, str]]:
    """Permanent invariant, checked for every node regardless of which
    service (if any) the current intent targets: the sum of every
    co-located service's effective cpu/ram footprint must not exceed the
    node's capacity. Returns one (ok, reason) pair per (node, resource) --
    same shape as csp_checks.py's other checks, for resolution_trace."""
    checks: list[tuple[bool, str]] = []
    for node_id, node in nodes.items():
        hosted = sorted(sid for sid in services if node_by_service.get(sid) == node_id)
        for node_field in ("cpu_cores", "ram_gb"):
            capacity = getattr(node, node_field)
            total = sum(
                effective_service_capacity(sid, node_field, services, active_requirements)
                for sid in hosted
            )
            ok = total <= capacity
            checks.append((
                ok,
                f"{node_field} on {node_id}: {total} of {capacity} used by {hosted} "
                f"{'ok' if ok else 'EXCEEDS capacity'}",
            ))
    return checks


def latency_satisfied(
    flows: dict[str, Flow],
    services: dict[str, Service],
    links: list[Link],
    active_requirements: list[Requirement],
    node_by_service: dict[str, str],
) -> list[tuple[bool, str]]:
    """Permanent invariant, checked for every flow that has an effective
    latency target (baseline or overridden by the current intent) --
    regardless of whether the current intent targets that specific flow."""
    checks: list[tuple[bool, str]] = []
    for flow_id, flow in flows.items():
        target = effective_flow_latency_target(flow_id, flows, active_requirements)
        if target is None:
            continue
        try:
            actual = flow_latency_ms(flow, links, node_by_service, services)
        except ValueError as exc:
            checks.append((False, f"flow {flow_id} latency: cannot evaluate -- {exc}"))
            continue
        ok = actual <= target
        checks.append((
            ok,
            f"flow {flow_id} latency: {actual}ms (budget {target}ms) {'ok' if ok else 'EXCEEDS budget'}",
        ))
    return checks
