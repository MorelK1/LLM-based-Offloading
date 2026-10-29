"""Shared helpers for reasoning over the application's pipeline.

The pipeline is the set of Flows (each an ordered chain of service_ids, see
schemas.py:Flow), laid over the physical nodes/links infrastructure. Several
flows may share services at their endpoints -- each flow is independently a
simple path, so there is no global merge-point restriction to enforce here.
Used by both necessity_checker.py (checking the current placement) and
decision_engine.py (the CSP model, checking candidate placements).
"""

import heapq
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


# vCPU is the canonical cpu unit -- "CPU"/"core"/"cores" are 1:1 synonyms,
# "millicore"/"mCPU"/"m" follow the Kubernetes convention (1000m = 1 vCPU).
_CPU_UNIT_FACTORS = {
    "vCPU": 1.0, "CPU": 1.0, "core": 1.0, "cores": 1.0,
    "millicore": 1 / 1000, "mCPU": 1 / 1000, "m": 1 / 1000,
}
# GB is the canonical ram unit, decimal (1 GB = 1000 MB = 1_000_000 KB = ...).
_RAM_UNIT_DECIMAL_FACTORS = {"KB": 1e-6, "MB": 1e-3, "GB": 1.0, "TB": 1e3}
# Binary units (IEC prefixes, powers of 1024) convert through real bytes,
# then down to decimal GB -- NOT a simple decimal factor (2048 MiB is
# 2.147483648 GB, not 2.048 GB).
_RAM_UNIT_BINARY_EXPONENTS = {"KiB": 10, "MiB": 20, "GiB": 30, "TiB": 40}
# ms is the canonical latency unit.
_LATENCY_UNIT_FACTORS = {"ms": 1.0, "µs": 1e-3, "us": 1e-3, "s": 1e3, "seconds": 1e3}


def to_native_unit(value: float, unit: str, kpi_type: str) -> float | None:
    """Converts a requirement's target_value into its KPI's canonical unit
    (cpu -> vCPU, ram -> GB, latency -> ms) -- e.g. a 20 MB ram target becomes
    0.02 GB before being compared to a node's ram_gb (an int, always in GB).

    Returns None when (kpi_type, unit) isn't a recognized pairing (e.g.
    unit="ms" with kpi_type="cpu") -- the caller's job to validate against,
    not something this function silently guesses at. See intent_grounding_node,
    which calls this immediately after extraction and drops any requirement
    this returns None for, same "drop rather than guess" policy as grounding.
    Idempotent on an already-canonical unit (factor 1.0), so later calls
    elsewhere in the pipeline on an already-normalized requirement are safe
    no-ops, not double conversions."""
    if kpi_type == "cpu":
        factor = _CPU_UNIT_FACTORS.get(unit)
    elif kpi_type == "ram":
        if unit in _RAM_UNIT_DECIMAL_FACTORS:
            factor = _RAM_UNIT_DECIMAL_FACTORS[unit]
        elif unit in _RAM_UNIT_BINARY_EXPONENTS:
            factor = (2 ** _RAM_UNIT_BINARY_EXPONENTS[unit]) / 1e9
        else:
            factor = None
    elif kpi_type == "latency":
        factor = _LATENCY_UNIT_FACTORS.get(unit)
    else:
        factor = None
    return value * factor if factor is not None else None


# The canonical unit written back onto a requirement after normalization --
# see intent_grounding_node.
CANONICAL_UNIT = {"cpu": "vCPU", "ram": "GB", "latency": "ms"}


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


def shortest_path_delays_ms(
    source: str, output_size: float | None, links: list[Link]
) -> dict[str, float]:
    """Dijkstra from source over the links graph: the minimum-delay path
    cost (transmission + propagation, summed per traversed link) to every
    other reachable node -- Equation 2's p_ij, computed once from source
    rather than once per (source, target) pair.

    output_size is the data volume carried over this hop (the upstream
    service's own output_size), in megabits (Mb) -- the same unit family as
    bandwidth_mbps (Mb/s), so output_size/bandwidth_mbps is seconds, and
    *1000 converts that to ms to match propagation_delay_ms. 0/undeclared
    means only propagation delay drives the weighting, consistent with
    every other quantity in this model defaulting to its simplest behavior
    when absent. A direct link is no longer required between two
    consecutive services -- only a node missing from the returned dict is
    genuinely unreachable from source (a disconnected infrastructure
    graph), which callers treat as infeasible."""
    size = output_size or 0.0
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for link in links:
        cost = (size / link.bandwidth_mbps) * 1000 + link.propagation_delay_ms
        adjacency.setdefault(link.source_node, []).append((link.target_node, cost))
        adjacency.setdefault(link.target_node, []).append((link.source_node, cost))

    best: dict[str, float] = {source: 0.0}
    frontier: list[tuple[float, str]] = [(0.0, source)]
    while frontier:
        dist, node = heapq.heappop(frontier)
        if dist > best.get(node, math.inf):
            continue
        for neighbor, cost in adjacency.get(node, []):
            new_dist = dist + cost
            if new_dist < best.get(neighbor, math.inf):
                best[neighbor] = new_dist
                heapq.heappush(frontier, (new_dist, neighbor))
    return best


def service_processing_delay_ms(service: Service, node: Node | None) -> float:
    """A single service's own processing delay, in ms, under its placement on
    node (None if unplaced/unknown -- treated the same as a node with no mips).

    Three cases, in priority order:
    1. service.wcet_ms set -- an explicit, placement-independent declared
       time, used as-is (overrides everything else).
    2. service.workload_mi set AND node.mips set -- the Latency Model's
       Equation 1, t_exec(s, pi(s)) = w(s) / p(pi(s)): workload (millions of
       instructions) divided by the hosting node's effective processing rate
       (millions of instructions/second), converted from seconds to ms.
       Assumes the node's full processing capacity is available to this one
       service -- no explicit modeling of CPU contention/queueing with other
       co-located services (same simplification the System Model states).
    3. Neither available -- 0.0, the original behavior, unchanged for any
       service/node that doesn't declare these (the toy example's earlier
       state, the ENACT scenario, public_safety)."""
    if service.wcet_ms is not None:
        return service.wcet_ms
    if service.workload_mi is not None and node is not None and node.mips:
        return (service.workload_mi / node.mips) * 1000
    return 0.0


def flow_latency_ms(
    flow: Flow,
    links: list[Link],
    node_by_service: dict[str, str],
    services: dict[str, Service],
    nodes: dict[str, Node],
) -> float:
    """Total end-to-end delay for the whole flow: processing_delay (sum of
    each service's own delay along flow.path, see service_processing_delay_ms
    -- 0 if neither wcet_ms nor workload_mi/node.mips is available, additive,
    no behavior change for services/nodes that don't set them) +
    communication_delay (sum of per-hop network delay, 0 for a co-located hop).

    Per-hop communication delay is Equation 2's minimum-delay path cost (see
    shortest_path_delays_ms): transmission (output_size in Mb / bandwidth_mbps,
    *1000 for ms -- 0 if the upstream service doesn't declare output_size)
    plus propagation (link.propagation_delay_ms), summed over every link on
    the cheapest path between the two services' nodes -- not just a direct
    link.

    node_by_service maps each service_id to the node it's hosted on --
    pass {sid: s.current_node for sid, s in services.items()} to evaluate the
    real, current placement, or a candidate/hypothetical placement (e.g. from
    the decision engine's search) to evaluate a placement being considered.
    Unlike wcet_ms, a workload_mi-derived delay is placement-dependent: it
    changes with node_by_service, since it depends on which node's mips is
    looked up for each service -- and so is the communication delay now,
    since the minimum-delay path depends on where both endpoints land.

    Consecutive services no longer need to be hosted on the same node or on
    directly linked nodes -- multi-hop routing is priced via
    shortest_path_delays_ms. The only remaining failure is two nodes with no
    path between them at all (a genuinely disconnected infrastructure graph).
    """
    processing_delay = sum(
        service_processing_delay_ms(services[sid], nodes.get(node_by_service.get(sid, "")))
        for sid in flow.path if sid in services
    )

    communication_delay = 0.0
    for upstream_id, downstream_id in flow_pairs(flow):
        node_a = node_by_service[upstream_id]
        node_b = node_by_service[downstream_id]
        if node_a == node_b:
            continue  # co-located, no network hop

        upstream_service = services.get(upstream_id)
        output_size = upstream_service.output_size if upstream_service is not None else None
        delays = shortest_path_delays_ms(node_a, output_size, links)
        if node_b not in delays:
            raise ValueError(
                f"No path between {node_a!r} and {node_b!r} "
                f"(consecutive services {upstream_id!r} -> {downstream_id!r}) -- "
                "the infrastructure graph is disconnected between these nodes."
            )
        communication_delay += delays[node_b]

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
    node_ids: set[str] | None = None,
) -> list[tuple[bool, str]]:
    """Permanent invariant, checked for every node in node_ids (every node
    in `nodes` if None, the default -- what the solvers use, since a search
    over hypothetical placements can land a service on any node) regardless
    of which service (if any) the current intent targets directly: the sum
    of every co-located service's effective cpu/ram footprint must not
    exceed the node's capacity. necessity_checker_node instead restricts
    node_ids to only the nodes hosting a service an active requirement
    targets -- the real, current placement can't develop a NEW capacity
    violation anywhere else, since nothing about an unrelated node's hosted
    services changed. Returns one (ok, reason) pair per (node, resource) --
    same shape as csp_checks.py's other checks, for resolution_trace."""
    checks: list[tuple[bool, str]] = []
    for node_id in (nodes.keys() if node_ids is None else node_ids):
        node = nodes.get(node_id)
        if node is None:
            continue
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
    nodes: dict[str, Node],
    flow_ids: set[str] | None = None,
) -> list[tuple[bool, str]]:
    """Permanent invariant, checked for every flow in flow_ids (every flow
    in `flows` if None, the default -- the solvers' own use) that has an
    effective latency target (baseline or overridden by the current intent)
    -- regardless of whether the current intent targets that specific flow
    directly. necessity_checker_node instead restricts flow_ids to flows an
    active latency requirement targets, plus flows containing a service an
    active cpu/ram requirement targets -- not relevant to latency under the
    current execution-time model (workload/mips, independent of cpu_cores),
    but scoped this way so a future cpu-affects-latency coupling doesn't
    need this restriction touched again."""
    checks: list[tuple[bool, str]] = []
    for flow_id in (flows.keys() if flow_ids is None else flow_ids):
        flow = flows.get(flow_id)
        if flow is None:
            continue
        target = effective_flow_latency_target(flow_id, flows, active_requirements)
        if target is None:
            continue
        try:
            actual = flow_latency_ms(flow, links, node_by_service, services, nodes)
        except ValueError as exc:
            checks.append((False, f"flow {flow_id} latency: cannot evaluate -- {exc}"))
            continue
        ok = actual <= target
        checks.append((
            ok,
            f"flow {flow_id} latency: {actual}ms (budget {target}ms) {'ok' if ok else 'EXCEEDS budget'}",
        ))
    return checks


def check_candidate_placement(
    candidate: dict[str, str],
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
    flows: dict[str, Flow],
) -> tuple[bool, list[tuple[bool, str]]]:
    """Runs every permanent invariant (capacity_satisfied, latency_satisfied)
    against one full candidate placement. Solver-agnostic -- used by
    csp_solver.py's brute-force search to validate a candidate during its
    own enumeration, and by decision_engine_cp_sat.py to explain CP-SAT's
    chosen solution the exact same way, after the fact. Returns (is_valid,
    checks); checks is the full (ok, reason) list, always collected in full
    even for an invalid candidate, so a rejected placement can be explained
    too."""
    checks: list[tuple[bool, str]] = []
    checks.extend(capacity_satisfied(nodes, services, requirements, candidate))
    checks.extend(latency_satisfied(flows, services, links, requirements, candidate, nodes))
    valid = all(ok for ok, _ in checks)
    return valid, checks


def explain_moved_services(
    candidate: dict[str, str],
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
    flows: dict[str, Flow],
) -> list[str]:
    """For every service candidate actually moves off its current node,
    explain why -- including services with no violated requirement of their
    own (moved only to keep another service's latency budget or a node's
    capacity satisfied).

    Checks the counterfactual: could this one service have stayed on its
    current node, given every OTHER service's placement in candidate? This
    is the evidence resolution_trace is otherwise missing -- it only ever
    records checks against the winning candidate, never against a rejected
    alternative, so without this a downstream consumer (e.g. explanation_node)
    has no grounded fact to cite for "why didn't it just stay put".

    Solver-agnostic: candidate can come from csp_solver.py's brute-force
    search or from decision_engine_cp_sat.py's solved assignment -- both
    produce a final, full service->node mapping, which is all this needs."""
    notes: list[str] = []
    for service_id in candidate:
        current_node = services[service_id].current_node
        if candidate[service_id] == current_node:
            continue  # didn't move, nothing to explain

        counterfactual = dict(candidate)
        counterfactual[service_id] = current_node
        ok, checks = check_candidate_placement(
            counterfactual, services, nodes, links, requirements, flows
        )
        if ok:
            notes.append(
                f"{service_id} did not strictly need to move off {current_node} "
                f"(staying would still satisfy every constraint) -- it moved only "
                f"because the search found a cheaper overall configuration"
            )
        else:
            failing = "; ".join(reason for check_ok, reason in checks if not check_ok)
            notes.append(f"{service_id} could not stay on {current_node}: {failing}")

    return notes
