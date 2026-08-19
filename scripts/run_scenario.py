"""Runs the LangGraph graph on the running example (scenario 1: real-time video analysis).

Usage:
    source venv/bin/activate
    python scripts/run_scenario.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.graph import build_graph  # noqa: E402
from agent.utils.config import load_config  # noqa: E402
from agent.utils.data_loader import load_links, load_nodes, load_services  # noqa: E402

INTENT = (
    "The detection model has been updated to a more accurate version, "
    "it now requires at least 12 vCPU and 24GB of RAM to run correctly."
)


def main() -> None:
    config = load_config()
    nodes = load_nodes(config.data.nodes_csv)
    links = load_links(config.data.links_csv)
    services = load_services(config.data.app_state_json)

    graph = build_graph()
    result = graph.invoke(
        {
            "intent_text": INTENT,
            "services": services,
            "nodes": nodes,
            "links": links,
            "requirements": [],
            "necessity_result": None,
            "decision_result": None,
            "explanation": None,
        }
    )

    print("=== Extracted requirements ===")
    for req in result["requirements"]:
        print(f"  {req.requirement_id}: {req.service} {req.kpi_type} {req.comparator} {req.target_value}{req.unit}")

    print("\n=== Necessity Checker ===")
    print(result["necessity_result"].model_dump_json(indent=2))

    if result["decision_result"]:
        print("\n=== Decision Engine ===")
        print(result["decision_result"].model_dump_json(indent=2))

    print("\n=== Explanation ===")
    print(result["explanation"])


if __name__ == "__main__":
    main()
