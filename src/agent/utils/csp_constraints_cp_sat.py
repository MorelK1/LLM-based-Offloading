"""CSP constraint builders for the Decision Engine (CP-SAT / OR-Tools).

Each function adds one family of hard constraints to a CpModel in place,
given the service -> node assignment variables `x` (x[service_id][node_id]
is a BoolVar, 1 iff that service is placed on that node). Kept separate from
decision_engine.py so each constraint family is independently readable.
"""

from ortools.sat.python import cp_model

from agent.model.schemas import Flow, Link, Node, Requirement, Service
from agent.utils.pipeline import (
    all_flow_pairs,
    effective_flow_latency_target,
    effective_service_capacity,
    flow_pairs,
    shortest_path_delays_ms,
)

_Assignment = dict[str, dict[str, cp_model.IntVar]]


def add_capacity_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    nodes: dict[str, Node],
    services: dict[str, Service],
    requirements: list[Requirement],
) -> None:
    """Permanent capacity invariant, for every node and every resource: the
    sum of every service's EFFECTIVE footprint (the current intent's target_value
    if it overrides that service+kpi, else its static baseline
    Service.requirements) must not exceed the node's capacity -- regardless
    of whether the current intent names that service at all. Mirrors
    pipeline.py:capacity_satisfied, expressed as a linear CP-SAT constraint
    instead of validating one already-chosen candidate.

    This is a single unconditional sum per (node, resource) -- no
    OnlyEnforceIf needed, since it's no longer "check only the actively
    required service", it's "every service always counts, wherever it ends
    up" (x[sid][node_id] selects whether sid's footprint applies to node_id).
    CP-SAT needs integer coefficients, so footprints/capacities are rounded.
    """
    for node_id, node in nodes.items():
        for node_field in ("cpu_cores", "ram_gb"):
            capacity = round(getattr(node, node_field))
            total = sum(
                round(effective_service_capacity(sid, node_field, services, requirements))
                * x[sid][node_id]
                for sid in services
            )
            model.Add(total <= capacity)


def add_fixed_placement_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    services: dict[str, Service],
) -> None:
    """Pins every service with fixed_placement=True to its current_node --
    combined with the "exactly one node per service" constraint the caller
    already adds, forcing x[sid][current_node]==1 forces every other
    x[sid][n] to 0, so the service can never appear as moved in a solution.
    """
    for sid, service in services.items():
        if service.fixed_placement:
            model.Add(x[sid][service.current_node] == 1)


def _processing_delay_terms_cp_sat(
    service_id: str,
    service: Service,
    x: _Assignment,
    nodes: dict[str, Node],
    node_ids: list[str],
):
    """CP-SAT linear expression for one service's own processing delay,
    mirroring pipeline.py:service_processing_delay_ms's priority order:
    wcet_ms (a placement-independent constant) first, else workload_mi
    divided by the chosen node's mips -- which, unlike wcet_ms, DOES depend
    on placement, so it's one weighted term per candidate node selected by
    x[service_id][n] rather than a single constant. Neither set -> 0,
    unchanged legacy behavior."""
    if service.wcet_ms is not None:
        return round(service.wcet_ms)
    if service.workload_mi is not None:
        terms = []
        for n in node_ids:
            node = nodes.get(n)
            if node is not None and node.mips:
                cost = round((service.workload_mi / node.mips) * 1000)
                terms.append(cost * x[service_id][n])
        if terms:
            return sum(terms)
    return 0


def add_latency_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    flows: dict[str, Flow],
    services: dict[str, Service],
    links: list[Link],
    requirements: list[Requirement],
    node_ids: list[str],
    nodes: dict[str, Node],
) -> None:
    """Constrain end-to-end delay for EVERY flow that has an effective
    latency target (the current intent's target_value if it targets that
    flow, else its static baseline Flow.requirements["latency"]) -- not just
    flows named in requirements, mirroring the capacity constraint above.
    Latency targets are always a ceiling in practice (see
    prompts/requirement_extraction.py), so this only ever adds "<=".

    Per-hop cost mirrors pipeline.py:flow_latency_ms's multi-hop model
    (shortest_path_delays_ms, Equation 2): transmission (output_size/
    bandwidth, 0 if the upstream service doesn't declare output_size) plus
    propagation (link.propagation_delay_ms), summed over the cheapest path
    between the two candidate nodes -- not just a direct link. One Dijkstra
    run per na (not per (na, nb) pair) gives every nb's cost in one pass.
    Processing delay is the sum of each service's own delay (see
    _processing_delay_terms_cp_sat) -- a constant when wcet_ms is declared,
    or one weighted term per candidate node when workload_mi/node.mips drive
    it instead, since that case IS placement-dependent, unlike wcet_ms.

    Also forbids, inline, placing two consecutive services on two nodes with
    NO PATH between them at all -- reusing the same Dijkstra call this
    function already makes for pricing (reachability doesn't depend on
    output_size, only cost does, so one call answers both questions). An
    unreachable pair has no hop-cost term to represent it, so without this
    the solver could otherwise treat it as free rather than infeasible --
    including for a flow with no active/baseline latency target to violate
    otherwise, which is why this lives here unconditionally rather than
    only under the per-flow loop below.
    """
    hop_cost_ms: dict[tuple[str, str], cp_model.IntVar] = {}
    for upstream, downstream in all_flow_pairs(list(flows.values())):
        upstream_service = services.get(upstream)
        output_size = upstream_service.output_size if upstream_service is not None else None
        pair_terms = []
        max_cost = 0
        for na in node_ids:
            delays = shortest_path_delays_ms(na, output_size, links)
            for nb in node_ids:
                if na == nb:
                    cost = 0
                elif nb in delays:
                    cost = round(delays[nb])
                else:
                    # No path at all: forbid this pair outright rather than
                    # silently leaving it unpriced (which would let the
                    # solver treat it as free).
                    model.Add(x[upstream][na] + x[downstream][nb] <= 1)
                    continue

                pair = model.NewBoolVar(f"pair_{upstream}_{na}__{downstream}_{nb}")
                model.AddMultiplicationEquality(pair, [x[upstream][na], x[downstream][nb]])
                pair_terms.append(cost * pair)
                max_cost = max(max_cost, cost)

        hop = model.NewIntVar(0, max_cost, f"hop_{upstream}__{downstream}")
        model.Add(hop == sum(pair_terms))
        hop_cost_ms[(upstream, downstream)] = hop

    for flow_id, flow in flows.items():
        target = effective_flow_latency_target(flow_id, flows, requirements)
        if target is None:
            continue
        processing_delay = sum(
            _processing_delay_terms_cp_sat(sid, services[sid], x, nodes, node_ids)
            for sid in flow.path if sid in services
        )
        cumulative = processing_delay + sum(hop_cost_ms[edge] for edge in flow_pairs(flow))
        model.Add(cumulative <= round(target))
