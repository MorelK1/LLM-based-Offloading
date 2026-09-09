"""Verification functions for the homemade CSP decision engine.

Unlike utils/csp_constraints_cp_sat.py (which builds symbolic constraints
for a solver to explore before any node is actually chosen), these functions
evaluate one already-concrete candidate value -- they're only usable once a
full candidate placement exists to check, which is exactly what
decision_engine.py's brute-force search does. Each returns (ok, reason) so
the resolution trace is kept, not just a boolean.
"""

from agent.model.schemas import Link, Node, Requirement
from agent.utils.pipeline import find_link


def _compare(actual: float, comparator: str, target: float) -> bool:
    if comparator == "gte":
        return actual >= target
    if comparator == "lte":
        return actual <= target
    return actual == target  # "eq"


def check_cpu(node: Node, req: Requirement) -> tuple[bool, str]:
    ok = _compare(node.cpu_cores, req.comparator, req.target_value)
    reason = (
        f"cpu for {req.service} on {node.node_id}: available {node.cpu_cores} "
        f"{'satisfies' if ok else 'does NOT satisfy'} {req.comparator} {req.target_value} "
        f"(requirement {req.requirement_id})"
    )
    return ok, reason


def check_ram(node: Node, req: Requirement) -> tuple[bool, str]:
    ok = _compare(node.ram_gb, req.comparator, req.target_value)
    reason = (
        f"ram for {req.service} on {node.node_id}: available {node.ram_gb} "
        f"{'satisfies' if ok else 'does NOT satisfy'} {req.comparator} {req.target_value} "
        f"(requirement {req.requirement_id})"
    )
    return ok, reason


def check_connectivity(node_a: str, node_b: str, links: list[Link]) -> tuple[bool, str]:
    if node_a == node_b:
        return True, f"co-located on {node_a}: no network hop needed"

    link = find_link(node_a, node_b, links)
    if link is None:
        return False, f"no direct link between {node_a} and {node_b}"
    return True, f"{node_a} <-> {node_b} linked via {link.link_id} ({link.latency_ms}ms)"


def check_latency(actual_ms: float, req: Requirement) -> tuple[bool, str]:
    ok = _compare(actual_ms, req.comparator, req.target_value)
    reason = (
        f"cumulative latency to {req.service}: {actual_ms}ms "
        f"{'satisfies' if ok else 'does NOT satisfy'} {req.comparator} {req.target_value}ms "
        f"(requirement {req.requirement_id})"
    )
    return ok, reason
