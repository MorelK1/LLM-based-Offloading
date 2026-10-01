"""Independently verifies a BaselineResult's proposed placement against our
REAL capacity/latency/connectivity checks (agent/utils/pipeline.py,
agent/utils/csp_checks.py) -- the LLM's own claim that its placement is
valid is never trusted at face value, exactly like the real pipeline never
trusts an unverified placement (decision_engine always checks candidates
before returning one).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for schema.py

from agent.model.schemas import Flow, Link, Node, Requirement, Service  # noqa: E402
from agent.utils.csp_checks import check_connectivity  # noqa: E402
from agent.utils.pipeline import all_flow_pairs, capacity_satisfied, latency_satisfied  # noqa: E402
from schema import BaselineResult  # noqa: E402


def requirement_from_baseline(result: BaselineResult) -> Requirement:
    return Requirement(
        requirement_id="baseline-req-001", target_type=result.target_type, target_id=result.target_id,
        kpi_type=result.kpi_type, comparator=result.comparator, target_value=result.target_value,
        unit=result.unit, source_span="(baseline, no source_span)",
    )


def verify_placement(
    nodes: dict[str, Node],
    services: dict[str, Service],
    flows: dict[str, Flow],
    links: list[Link],
    requirement: Requirement,
    placement: dict[str, str],
) -> tuple[bool, list[tuple[bool, str]]]:
    """placement: the LLM's proposed new_placement (service_id -> node_id),
    already backfilled with current_node for any service it omitted (see
    run_sample.py) -- an incomplete placement from the LLM is a formatting
    problem, not grounds to skip verification of what IS given."""
    checks: list[tuple[bool, str]] = []
    checks.extend(capacity_satisfied(nodes, services, [requirement], placement))
    checks.extend(latency_satisfied(flows, services, links, [requirement], placement))
    for upstream, downstream in all_flow_pairs(list(flows.values())):
        if upstream in placement and downstream in placement:
            checks.append(check_connectivity(placement[upstream], placement[downstream], links))
    ok = all(c_ok for c_ok, _ in checks)
    return ok, checks
