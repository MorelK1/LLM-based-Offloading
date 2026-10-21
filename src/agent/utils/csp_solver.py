"""Homemade brute-force CSP solver for the Decision Engine.

Enumerates every candidate full placement (one node per service) and keeps
the one that moves the fewest services from their current node. Ties
between equally-disruptive candidates are not broken by anything (no
infrastructure-tier preference) -- the first one reached in enumeration
order is kept. Validity is checked per-candidate via
pipeline.py:check_candidate_placement (capacity_satisfied/latency_satisfied
under the hood), and a moved service's reason via
pipeline.py:explain_moved_services -- both solver-agnostic, shared with
decision_engine_cp_sat.py so CP-SAT's chosen solution gets the exact same
human-readable resolution trace.

A CP-SAT/OR-Tools implementation of the same problem exists as an
alternative backend in nodes/decision_engine_cp_sat.py /
utils/csp_constraints_cp_sat.py.
"""

import itertools

from agent.model.schemas import Flow, Link, Node, Requirement, Service
from agent.utils.pipeline import check_candidate_placement, explain_moved_services


def solve_placement(
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
    flows: dict[str, Flow],
) -> tuple[dict[str, str] | None, list[str], list[str]]:
    """Search every candidate placement (len(nodes) ** len(services)
    combinations, trivial for the running example's size) and return
    (best_placement, resolution_trace, search_trace) for the least-disruptive
    valid one.

    resolution_trace explains why the returned placement is valid (the
    winning candidate's checks). search_trace instead documents the search
    process itself -- unlike a pruning backtracking search, this brute-force
    search doesn't skip candidates early, so logging every one of the
    len(nodes) ** len(services) attempts would be unreadable noise; only
    genuine improvements (a new best-so-far) are logged, plus a summary.

    Returns (None, [], search_trace) if no candidate satisfies every
    constraint -- never raises, so the caller can turn that into an
    INFEASIBLE DecisionResult instead of the pipeline crashing outright.
    """
    service_ids = list(services.keys())
    node_ids = list(nodes.keys())

    total = len(node_ids) ** len(service_ids)
    search_trace = [
        f"exploring {total} candidate placements "
        f"({len(node_ids)} nodes ^ {len(service_ids)} services)"
    ]

    best_candidate: dict[str, str] | None = None
    best_reasons: list[str] = []
    best_moved: int | None = None
    tried = 0
    valid_count = 0

    for node_choice in itertools.product(node_ids, repeat=len(service_ids)):
        tried += 1
        candidate = dict(zip(service_ids, node_choice))

        valid, checks = check_candidate_placement(
            candidate, services, nodes, links, requirements, flows
        )
        if not valid:
            continue
        valid_count += 1

        moved = sum(1 for s in service_ids if candidate[s] != services[s].current_node)

        if best_moved is None or moved < best_moved:
            search_trace.append(
                f"candidate #{tried} {candidate} (moved={moved}) is the new best so far"
            )
            best_moved = moved
            best_candidate = candidate
            best_reasons = [reason for _ok, reason in checks]

    if best_candidate is None:
        search_trace.append(
            f"explored {tried} candidates, none valid -- "
            "no placement satisfies the cpu/ram/latency constraints"
        )
        return None, [], search_trace

    search_trace.append(
        f"explored {tried} candidates ({valid_count} valid), "
        f"kept {best_candidate} as the least-disruptive valid one"
    )

    best_reasons += explain_moved_services(
        best_candidate, services, nodes, links, requirements, flows
    )

    return best_candidate, best_reasons, search_trace


def diagnose_node_options(
    service_id: str,
    services: dict[str, Service],
    nodes: dict[str, Node],
    links: list[Link],
    requirements: list[Requirement],
    flows: dict[str, Flow],
) -> dict:
    """Standalone diagnostic, independent of solve_placement's search: for
    one service, try every node as its hypothetical placement (holding every
    other service fixed at its current node) and report which ones would be
    valid and why/why not.

    Answers "why not node X for this service?" without needing to interpret
    a full solve_placement run. Reuses check_candidate_placement, so a node can be
    rejected here not just for its own cpu/ram, but also for breaking the
    latency budget of a downstream service on this one's pipeline path.
    """
    current_placement = {sid: s.current_node for sid, s in services.items()}

    trace: dict[str, dict] = {}
    valid_nodes: list[str] = []

    for node_id in nodes:
        candidate = {**current_placement, service_id: node_id}
        accepted, checks = check_candidate_placement(
            candidate, services, nodes, links, requirements, flows
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
