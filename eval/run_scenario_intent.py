"""Runs ONE real natural-language intent through the REAL, FULL graph
(intent_grounding -> necessity_checker -> decision_engine -> explanation)
against one eval/experiment_150 scenario's system model -- a single manual
sanity check before building out the full 150-scenario campaign.

Usage:
    source venv/bin/activate
    PYTHONPATH=src python3 eval/run_scenario_intent.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "system_model"))

from agent.graph import build_graph  # noqa: E402
from loader import load_flows, load_links, load_nodes, load_scenario, load_services  # noqa: E402

SCENARIO_ID = "ARVR-000035"
INTENT = "Rebalancing the latency budgets: the recognition flow gets tighter, 464.432 ms at most, while the AR rendering flow gets a bit more room, 504.481 ms at most. Separately, the stage in the middle of both chains needs at least 6580.976 millicores, and the first stage after capture in the recognition chain at least 2.820437067 GB of RAM."  # <- à remplir avec l'intent envoyé


def main() -> None:
    if not INTENT.strip():
        raise SystemExit("Remplis la constante INTENT avant de lancer ce script.")

    scenario = load_scenario(SCENARIO_ID)
    nodes = load_nodes()
    links = load_links()
    services = load_services(scenario)
    flows = load_flows(scenario)

    graph = build_graph()
    result = graph.invoke(
        {
            "intent_text": INTENT,
            "services": services,
            "flows": flows,
            "nodes": nodes,
            "links": links,
            "requirements": [],
            "necessity_result": None,
            "decision_result": None,
            "explanation": None,
        }
    )

    print("=== Scenario ground truth ===")
    print(f"  id={scenario['id']}  category={scenario['category']}  decision={scenario['decision']}")
    print(f"  moved_components={scenario['moved_components']}  p1={scenario['p1']}")
    print(f"  requirements={scenario['requirements']}")

    print("\n=== Extracted requirements ===")
    for req in result["requirements"]:
        print(
            f"  {req.requirement_id}: {req.target_type}:{req.target_id} "
            f"{req.kpi_type} {req.comparator} {req.target_value}{req.unit} "
            f'(source: "{req.source_span}")'
        )

    print("\n=== Necessity Checker ===")
    print(result["necessity_result"].model_dump_json(indent=2))

    if result["decision_result"]:
        print("\n=== Decision Engine ===")
        print(result["decision_result"].model_dump_json(indent=2))

    print("\n=== Explanation ===")
    print(result["explanation"])


if __name__ == "__main__":
    main()
