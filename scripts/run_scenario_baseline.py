"""Runs the single-LLM baseline (expérimentations/public_safety/baseline/) on
the same toy scenario as run_scenario.py (scenario 1: real-time video
analysis), for a direct side-by-side with the real four-node pipeline.

Usage:
    source venv/bin/activate
    python scripts/run_scenario_baseline.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "expérimentations" / "public_safety" / "baseline"))

from agent.utils.config import load_config  # noqa: E402
from agent.utils.data_loader import load_flows, load_links, load_nodes, load_services  # noqa: E402
from runner import run_baseline  # noqa: E402
from verifier import requirements_from_baseline, verify_placement  # noqa: E402

INTENT = (
    "The detection model has been updated to a more accurate version, "
    "it now requires at least 12 vCPU and 24GB of RAM to run correctly."
)


def main() -> None:
    config = load_config()
    nodes = load_nodes(config.data.nodes_csv)
    links = load_links(config.data.links_csv)
    services = load_services(config.data.app_state_json)
    flows = load_flows(config.data.flows_json)

    outcome = run_baseline(INTENT, services, flows, nodes, links)
    result = outcome["result"]

    print("=== Baseline result ===")
    if result is None:
        print(f"PARSING FAILED -- {outcome['parsing_error']}")
        return

    print("extracted requirements:")
    for r in result.requirements:
        print(f"  {r.target_type}:{r.target_id} {r.kpi_type} {r.comparator} {r.target_value}{r.unit}"
              f" (source: \"{r.source_span}\")")
    print(f"outcome: {result.outcome}")
    print(f"proposed new_placement: {result.new_placement}")
    print(f"model={outcome['model']} elapsed={outcome['elapsed_s']:.2f}s tokens={outcome['token_usage']}")

    full_placement = {sid: result.new_placement.get(sid, s.current_node) for sid, s in services.items()}
    requirements = requirements_from_baseline(result)
    feasible, checks = verify_placement(nodes, services, flows, links, requirements, full_placement)

    print(f"\n=== Independent verification (placement_feasible={feasible}) ===")
    for ok, reason in checks:
        print(f"  {'ok' if ok else 'FAIL'}: {reason}")

    print("\n=== Baseline explanation ===")
    print(result.explanation)


if __name__ == "__main__":
    main()
