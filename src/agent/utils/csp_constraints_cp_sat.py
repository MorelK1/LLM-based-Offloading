"""CSP constraint builders for the Decision Engine (CP-SAT / OR-Tools).

Each function adds one family of hard constraints to a CpModel in place,
given the service -> node assignment variables `x` (x[service_id][node_id]
is a BoolVar, 1 iff that service is placed on that node). Kept separate from
decision_engine.py so each constraint family is independently readable.
"""

from ortools.sat.python import cp_model

from agent.model.schemas import Link, Node, Requirement, Service
from agent.utils.pipeline import build_predecessor_map, chain_to, find_link

_Assignment = dict[str, dict[str, cp_model.IntVar]]


def _satisfies(req: Requirement, value: float) -> bool:
    if req.comparator == "gte":
        return value >= req.target_value
    if req.comparator == "lte":
        return value <= req.target_value
    return value == req.target_value  # "eq"


def add_cpu_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    requirements: list[Requirement],
    nodes: dict[str, Node],
) -> None:
    """Forbid assigning a service to a node without enough cpu_cores."""
    for req in requirements:
        if req.kpi_type != "cpu":
            continue
        for node_id, node in nodes.items():
            if not _satisfies(req, node.cpu_cores):
                model.Add(x[req.service][node_id] == 0)


def add_ram_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    requirements: list[Requirement],
    nodes: dict[str, Node],
) -> None:
    """Forbid assigning a service to a node without enough ram_gb."""
    for req in requirements:
        if req.kpi_type != "ram":
            continue
        for node_id, node in nodes.items():
            if not _satisfies(req, node.ram_gb):
                model.Add(x[req.service][node_id] == 0)


def add_connectivity_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    services: dict[str, Service],
    links: list[Link],
    node_ids: list[str],
) -> None:
    """Forbid placing two consecutive pipeline services (per Service.next_services)
    on two nodes that aren't directly linked. Co-location (same node) is always
    allowed. No multi-hop routing yet -- see README "Known limitations".

    Must be applied together with add_latency_constraints_cp_sat: this function only
    forbids disconnected placements, it doesn't price the connected ones.
    """
    predecessors = build_predecessor_map(services)
    for downstream, upstream in predecessors.items():
        for na in node_ids:
            for nb in node_ids:
                if na == nb:
                    continue
                if find_link(na, nb, links) is None:
                    model.Add(x[upstream][na] + x[downstream][nb] <= 1)


def add_latency_constraints_cp_sat(
    model: cp_model.CpModel,
    x: _Assignment,
    services: dict[str, Service],
    links: list[Link],
    requirements: list[Requirement],
    node_ids: list[str],
) -> None:
    """Constrain cumulative end-to-end latency (pipeline root -> service) for
    every "latency" requirement, based on which node each service along the
    way ends up on (0ms per hop if co-located, else the link's latency_ms).

    Must be applied together with add_connectivity_constraints_cp_sat: this function
    prices connected node pairs but does not forbid disconnected ones itself.
    """
    predecessors = build_predecessor_map(services)

    hop_latency_ms: dict[tuple[str, str], cp_model.IntVar] = {}
    for downstream, upstream in predecessors.items():
        pair_terms = []
        max_latency = 0
        for na in node_ids:
            for nb in node_ids:
                if na == nb:
                    cost = 0
                else:
                    link = find_link(na, nb, links)
                    if link is None:
                        continue  # disallowed by add_connectivity_constraints_cp_sat
                    cost = round(link.latency_ms)

                pair = model.NewBoolVar(f"pair_{upstream}_{na}__{downstream}_{nb}")
                model.AddMultiplicationEquality(pair, [x[upstream][na], x[downstream][nb]])
                pair_terms.append(cost * pair)
                max_latency = max(max_latency, cost)

        hop = model.NewIntVar(0, max_latency, f"hop_{upstream}__{downstream}")
        model.Add(hop == sum(pair_terms))
        hop_latency_ms[(upstream, downstream)] = hop

    for req in requirements:
        if req.kpi_type != "latency":
            continue
        chain = chain_to(req.service, predecessors)
        cumulative = sum(hop_latency_ms[edge] for edge in zip(chain, chain[1:]))
        target = round(req.target_value)
        if req.comparator == "lte":
            model.Add(cumulative <= target)
        elif req.comparator == "gte":
            model.Add(cumulative >= target)
        elif req.comparator == "eq":
            model.Add(cumulative == target)
