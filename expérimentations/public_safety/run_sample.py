"""Runs ONE public_safety e2e_v2 sample through the REAL pipeline nodes
(necessity_checker_node, decision_engine_node -- no reimplementation) and
compares the outcome to the sample's own ground truth.

Mirrors graph.py's real routing: decision_engine_node is only called when
necessity_checker_node finds reconfiguration_required, exactly like the
real graph -- a "no_action_needed" case never reaches it.

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/run_sample.py PS-E2E-0001
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.nodes.decision_engine import decision_engine_node  # noqa: E402
from agent.nodes.necessity_checker import necessity_checker_node  # noqa: E402
from loader import (  # noqa: E402
    load_links,
    load_nodes,
    load_sample,
    load_services_and_flows,
    requirement_from_sample,
)

# public_safety's outcome vocabulary (STAY/OFFLOAD/INFEASIBLE) maps onto our
# two-field result (necessity_result.status, decision_result.outcome).
_OUTCOME_MAP = {
    ("no_action_needed", None): "STAY",
    ("reconfiguration_required", "FEASIBLE"): "OFFLOAD",
    ("reconfiguration_required", "INFEASIBLE"): "INFEASIBLE",
}


def run(sample_id: str) -> bool:
    sample = load_sample(sample_id)
    req = requirement_from_sample(sample)
    initial_placement = sample["ground_truth"]["reconfiguration"]["initial_placement"]

    nodes = load_nodes(sample["infrastructure_id"])
    links = load_links(sample["infrastructure_id"])
    services, flows = load_services_and_flows(sample["application_context_id"], initial_placement)

    state = {"services": services, "flows": flows, "nodes": nodes, "links": links, "requirements": [req]}
    nres = necessity_checker_node(state)["necessity_result"]

    decision_outcome = None
    moved: list[str] = []
    if nres.status == "reconfiguration_required":
        state["necessity_result"] = nres
        dres = decision_engine_node(state)["decision_result"]
        decision_outcome = dres.outcome
        moved = sorted(dres.decision.keys())

    our_outcome = _OUTCOME_MAP[(nres.status, decision_outcome)]
    expected_outcome = sample["ground_truth"]["outcome"]
    match = our_outcome == expected_outcome

    print(f"{sample_id}: {sample['intent']['text']!r}")
    print(f"  necessity={nres.status} decision={decision_outcome} -> {our_outcome} (expected {expected_outcome})")
    if moved:
        print(f"  moved: {moved}")
    print(f"  {'MATCH' if match else 'MISMATCH'}")
    return match


if __name__ == "__main__":
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "PS-E2E-0001"
    run(sample_id)
