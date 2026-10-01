"""CSP constraint builders for the Decision Engine (CP-SAT / OR-Tools).

Each function adds one family of hard constraints to a CpModel in place,
given the service -> node assignment variables `x` (x[service_id][node_id]
is a BoolVar, 1 iff that service is placed on that node). Kept separate from
decision_engine.py so each constraint family is independently readable.
"""

import math

from ortools.sat.python import cp_model

from agent.model.schemas import Flow, Link, Node, Requirement, Service
from agent.utils.pipeline import (
    all_flow_pairs,
    effective_flow_latency_target,
    effective_service_capacity,
    find_link,
    flow_pairs,
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


def add_connectivity_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    flows: dict[str, Flow],
    links: list[Link],
    node_ids: list[str],
) -> None:
    """Forbid placing two consecutive services of any Flow.path on two nodes
    that aren't directly linked. Co-location (same node) is always allowed.
    No multi-hop routing yet -- see README "Known limitations".

    Must be applied together with add_latency_constraints_cp_sat: this function only
    forbids disconnected placements, it doesn't price the connected ones.
    """
    for upstream, downstream in all_flow_pairs(list(flows.values())):
        for na in node_ids:
            for nb in node_ids:
                if na == nb:
                    continue
                if find_link(na, nb, links) is None:
                    model.Add(x[upstream][na] + x[downstream][nb] <= 1)


def add_latency_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    flows: dict[str, Flow],
    services: dict[str, Service],
    links: list[Link],
    requirements: list[Requirement],
    node_ids: list[str],
) -> None:
    """Constrain end-to-end delay for EVERY flow that has an effective
    latency target (the current intent's target_value if it targets that
    flow, else its static baseline Flow.requirements["latency"]) -- not just
    flows named in requirements, mirroring the capacity constraint above.
    Latency targets are always a ceiling in practice (see
    prompts/requirement_extraction.py), so this only ever adds "<=".

    Per-hop cost mirrors pipeline.py:flow_latency_ms's dual model: if the
    upstream service declares output_size, cost = ceil(output_size /
    link.bandwidth_mbps); otherwise cost = the link's static latency_ms.
    Processing delay (sum of wcet_ms along the flow) doesn't depend on node
    placement, so it's added as a constant offset, not a per-hop CP-SAT term.

    Must be applied together with add_connectivity_constraints_cp_sat: this function
    prices connected node pairs but does not forbid disconnected ones itself.
    """
    hop_cost_ms: dict[tuple[str, str], cp_model.IntVar] = {}
    for upstream, downstream in all_flow_pairs(list(flows.values())):
        upstream_service = services.get(upstream)
        pair_terms = []
        max_cost = 0
        for na in node_ids:
            for nb in node_ids:
                if na == nb:
                    cost = 0
                else:
                    link = find_link(na, nb, links)
                    if link is None:
                        continue  # disallowed by add_connectivity_constraints_cp_sat
                    if upstream_service is not None and upstream_service.output_size is not None:
                        cost = math.ceil(upstream_service.output_size / link.bandwidth_mbps)
                    else:
                        cost = round(link.latency_ms)

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
        processing_delay = round(sum((services[sid].wcet_ms or 0.0) for sid in flow.path if sid in services))
        cumulative = processing_delay + sum(hop_cost_ms[edge] for edge in flow_pairs(flow))
        model.Add(cumulative <= round(target))
