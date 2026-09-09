"""Homemade brute-force CSP solver for the Decision Engine.

Enumerates every candidate full placement (one node per service) and keeps
the cheapest valid one: fewest services moved from their current node first,
lowest total infrastructure tier cost as a tie-breaker. Validity is checked
per-candidate via csp_checks.py, which keeps a human-readable resolution
trace for the chosen placement.

A CP-SAT/OR-Tools implementation of the same problem exists as a reference
in nodes/decision_engine_cp_sat.py / utils/csp_constraints_cp_sat.py.
"""

import itertools

from agent.model.schemas import Link, Node, Requirement, Service
from agent.utils.csp_checks import check_connectivity, check_cpu, check_latency, check_ram
from agent.utils.pipeline import build_predecessor_map, cumulative_latency_ms

_TIER_ORDER = {"iot": 0, "edge": 1, "fog": 2, "cloud": 3}


def _check_candidate(
    candidate: dict[str, str],
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
    predecessors: dict[str, str],
) -> tuple[bool, list[tuple[bool, str]]]:
    """Run every check against one full candidate placement.

    Returns (is_valid, checks) -- checks is the full (ok, reason) pair per
    verification, always collected in full even for an invalid candidate, so
    a rejected placement can be explained too.
    """
    checks: list[tuple[bool, str]] = []
    valid = True

    for req in requirements:
        node = nodes[candidate[req.service]]
        if req.kpi_type == "cpu":
            ok, reason = check_cpu(node, req)
        elif req.kpi_type == "ram":
            ok, reason = check_ram(node, req)
        elif req.kpi_type == "latency":
            try:
                actual_ms = cumulative_latency_ms(req.service, services, links, candidate)
            except ValueError as exc:
                # A candidate placement routinely breaks connectivity during
                # brute-force search (unlike necessity_checker, which only
                # ever evaluates the one real, already-deployed placement) --
                # that's just an invalid candidate here, not an error.
                ok, reason = False, f"cannot evaluate latency for {req.service}: {exc}"
            else:
                ok, reason = check_latency(actual_ms, req)
        else:
            continue
        checks.append((ok, reason))
        valid = valid and ok

    for downstream, upstream in predecessors.items():
        ok, reason = check_connectivity(candidate[upstream], candidate[downstream], links)
        checks.append((ok, reason))
        valid = valid and ok

    return valid, checks


def solve_placement(
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
) -> tuple[dict[str, str], list[str], list[str]]:
    """Search every candidate placement (len(nodes) ** len(services)
    combinations, trivial for the running example's size) and return
    (best_placement, resolution_trace, search_trace) for the cheapest valid
    one.

    resolution_trace explains why the returned placement is valid (the
    winning candidate's checks). search_trace instead documents the search
    process itself -- unlike a pruning backtracking search, this brute-force
    search doesn't skip candidates early, so logging every one of the
    len(nodes) ** len(services) attempts would be unreadable noise; only
    genuine improvements (a new best-so-far) are logged, plus a summary.

    Raises ValueError if no candidate satisfies every constraint.
    """
    service_ids = list(services.keys())
    node_ids = list(nodes.keys())
    predecessors = build_predecessor_map(services)

    total = len(node_ids) ** len(service_ids)
    search_trace = [
        f"exploring {total} candidate placements "
        f"({len(node_ids)} nodes ^ {len(service_ids)} services)"
    ]

    best_candidate: dict[str, str] | None = None
    best_reasons: list[str] = []
    best_score: tuple[int, int] | None = None
    tried = 0
    valid_count = 0

    for node_choice in itertools.product(node_ids, repeat=len(service_ids)):
        tried += 1
        candidate = dict(zip(service_ids, node_choice))

        valid, checks = _check_candidate(
            candidate, services, nodes, links, requirements, predecessors
        )
        if not valid:
            continue
        valid_count += 1

        moved = sum(1 for s in service_ids if candidate[s] != services[s].current_node)
        infra_cost = sum(_TIER_ORDER[nodes[candidate[s]].tier] for s in service_ids)
        score = (moved, infra_cost)  # fewest moves first, then cheapest tiers

        if best_score is None or score < best_score:
            search_trace.append(
                f"candidate #{tried} {candidate} (moved={moved}, infra_cost={infra_cost}) "
                f"is the new best so far"
            )
            best_score = score
            best_candidate = candidate
            best_reasons = [reason for _ok, reason in checks]

    if best_candidate is None:
        search_trace.append(f"explored {tried} candidates, none valid")
        raise ValueError(
            "No placement satisfies the cpu/ram/connectivity/latency constraints."
        )

    search_trace.append(
        f"explored {tried} candidates ({valid_count} valid), "
        f"kept {best_candidate} as the cheapest valid one"
    )

    best_reasons += _explain_moved_services(
        best_candidate, services, nodes, links, requirements, predecessors
    )

    return best_candidate, best_reasons, search_trace


def _explain_moved_services(
    best_candidate: dict[str, str],
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
    predecessors: dict[str, str],
) -> list[str]:
    """For every service the search actually moved, explain why -- including
    services with no violated requirement of their own (moved only to keep
    another service connected/within latency budget).

    Checks the counterfactual: could this one service have stayed on its
    current node, given every OTHER service's final chosen placement? This
    is the evidence resolution_trace is otherwise missing -- it only ever
    records checks against the winning candidate, never against a rejected
    alternative, so without this a downstream consumer (e.g. explanation_node)
    has no grounded fact to cite for "why didn't it just stay put".
    """
    notes: list[str] = []
    for service_id in best_candidate:
        current_node = services[service_id].current_node
        if best_candidate[service_id] == current_node:
            continue  # didn't move, nothing to explain

        counterfactual = dict(best_candidate)
        counterfactual[service_id] = current_node
        ok, checks = _check_candidate(
            counterfactual, services, nodes, links, requirements, predecessors
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


def diagnose_node_options(
    service_id: str,
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
) -> dict:
    """Standalone diagnostic, independent of solve_placement's search: for
    one service, try every node as its hypothetical placement (holding every
    other service fixed at its current node) and report which ones would be
    valid and why/why not.

    Answers "why not node X for this service?" without needing to interpret
    a full solve_placement run. Reuses _check_candidate, so a node can be
    rejected here not just for its own cpu/ram, but also for breaking
    connectivity/latency for a downstream service on this one's pipeline
    path.
    """
    predecessors = build_predecessor_map(services)
    current_placement = {sid: s.current_node for sid, s in services.items()}

    trace: dict[str, dict] = {}
    valid_nodes: list[str] = []

    for node_id in nodes:
        candidate = {**current_placement, service_id: node_id}
        accepted, checks = _check_candidate(
            candidate, services, nodes, links, requirements, predecessors
        )
        trace[node_id] = {"accepted": accepted, "checks": checks}
        if accepted:
            valid_nodes.append(node_id)

    return {"valid_nodes": valid_nodes, "trace": trace}


def format_diagnosis(service_id: str, diagnosis: dict) -> str:
    """Pretty-print a diagnose_node_options() result -- one block per node,
    ACCEPTED/REJECTED plus every check's reason. Unlike resolution_trace/
    search_trace (already flat list[str], trivial to print as-is), this
    trace is a nested per-node structure that's unreadable printed raw.
    """
    lines = [f"Diagnosis for {service_id}:"]
    for node_id, info in diagnosis["trace"].items():
        status = "ACCEPTED" if info["accepted"] else "REJECTED"
        lines.append(f"  {node_id}: {status}")
        for ok, reason in info["checks"]:
            lines.append(f"    [{'ok' if ok else 'FAIL'}] {reason}")
    return "\n".join(lines)
