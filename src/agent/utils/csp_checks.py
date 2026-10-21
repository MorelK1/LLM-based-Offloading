"""Verification functions for the homemade CSP decision engine.

Unlike utils/csp_constraints_cp_sat.py (which builds symbolic constraints
for a solver to explore before any node is actually chosen), these functions
evaluate one already-concrete candidate value -- they're only usable once a
full candidate placement exists to check, which is exactly what
decision_engine.py's brute-force search does. Each returns (ok, reason) so
the resolution trace is kept, not just a boolean.

cpu/ram and latency checks used to live here too (check_cpu/check_ram/
check_latency), but they're now permanent invariants checked for every
service/flow regardless of the current intent -- see
pipeline.py:capacity_satisfied/latency_satisfied, used directly by
csp_solver.py.

check_connectivity's direct-link-only notion of connectivity is no longer
what the real pipeline uses (csp_solver.py now relies on
pipeline.py:flow_latency_ms's multi-hop routing instead, via
shortest_path_delays_ms) -- this function is kept only because
expérimentations/public_safety/baseline/verifier.py still depends on its
original, stricter semantics to score the already-evaluated baseline
campaign the way it was actually run.
"""

from agent.model.schemas import Link
from agent.utils.pipeline import find_link


def check_connectivity(node_a: str, node_b: str, links: list[Link]) -> tuple[bool, str]:
    if node_a == node_b:
        return True, f"co-located on {node_a}: no network hop needed"

    link = find_link(node_a, node_b, links)
    if link is None:
        return False, f"no direct link between {node_a} and {node_b}"
    return True, f"{node_a} <-> {node_b} linked via {link.link_id} ({link.propagation_delay_ms}ms)"
