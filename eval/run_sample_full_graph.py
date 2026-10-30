"""Runs ONE eval/experiment_150 scenario through the REAL, FULL graph
(intent_grounding -> necessity_checker -> decision_engine -> explanation),
real LLM calls included -- unlike eval/run_scenario_intent.py, which uses a
hand-typed intent, this pulls the already-generated intent from
intent/intents.json by scenario_id.

Persists a COMPLETE raw record (not just a verdict) -- every field of every
extracted requirement, the full ground truth (requirements, decision,
moved_components, p1), and per-call timing/token usage. No metric (exact
match, F1...) is computed here -- this only captures what a later, separate
scoring script will need, same split as
expérimentations/public_safety/run_sample_full_graph.py.

model/explanation_model/prompt_strategy are left unset by default (None),
which build_graph resolves to OPENROUTER_MODEL (.env) -- pass --model (and
optionally --explanation-model) to pick a specific OpenRouter model per run
without touching this file.

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 eval/run_sample_full_graph.py ARVR-000001 \\
        [--model MODEL] [--prompt-strategy STRATEGY] [--explanation-model MODEL]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "system_model"))

from agent.graph import build_graph  # noqa: E402
from loader import load_flows, load_intent, load_links, load_nodes, load_scenario, load_services  # noqa: E402

DEFAULT_SCENARIO_ID = "ARVR-000001"


def run(
    scenario_id: str,
    graph=None,
    model: str | None = None,
    prompt_strategy: str = "zero_shot",
    explanation_model: str | None = None,
    verbose: bool = False,
) -> dict:
    scenario = load_scenario(scenario_id)
    intent_entry = load_intent(scenario_id)

    nodes = load_nodes()
    links = load_links()
    services = load_services(scenario)
    flows = load_flows(scenario)

    if graph is None:
        graph = build_graph(model=model, prompt_strategy=prompt_strategy, explanation_model=explanation_model)

    start = time.perf_counter()
    result = graph.invoke(
        {
            "intent_text": intent_entry["intent"],
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
    total_elapsed_s = time.perf_counter() - start

    record = {
        "run_config": {"model": model, "prompt_strategy": prompt_strategy, "explanation_model": explanation_model},
        "scenario_id": scenario_id,
        "intent": intent_entry["intent"],
        "intent_metadata": {
            k: intent_entry.get(k) for k in ("plan", "mentions", "n_words", "review_status", "variant_id")
        },
        "extracted_requirements": [req.model_dump() for req in result["requirements"]],
        "necessity_result": result["necessity_result"].model_dump() if result["necessity_result"] else None,
        "decision_result": result["decision_result"].model_dump() if result["decision_result"] else None,
        "explanation": result["explanation"],
        "extraction_model": result.get("extraction_model"),
        "extraction_elapsed_s": result.get("extraction_elapsed_s"),
        "extraction_token_usage": result.get("extraction_token_usage"),
        "extraction_parsing_error": result.get("extraction_parsing_error"),
        "explanation_model": result.get("explanation_model"),
        "explanation_elapsed_s": result.get("explanation_elapsed_s"),
        "explanation_token_usage": result.get("explanation_token_usage"),
        "total_elapsed_s": total_elapsed_s,
        # Never fed to the model -- captured here only so a later scoring
        # script can compare without re-running anything.
        "ground_truth": {
            "requirements": scenario["requirements"],
            "decision": scenario["decision"],
            "moved_components": scenario["moved_components"],
            "p1": scenario["p1"],
            "feasible_placements": scenario.get("feasible_placements"),
            "minimum_migrations": scenario.get("minimum_migrations"),
            "category": scenario.get("category"),
            "level": scenario.get("level"),
        },
    }

    if verbose:
        print(f"=== {scenario_id} ({total_elapsed_s:.1f}s) ===")
        print(f"intent: {intent_entry['intent']}")
        print(f"ground truth: decision={scenario['decision']} moved={scenario['moved_components']} p1={scenario['p1']}")
        print(f"extracted requirements: {record['extracted_requirements']}")
        print(f"necessity_result: {record['necessity_result']}")
        print(f"decision_result: {record['decision_result']}")
        print(f"explanation: {record['explanation']}")

    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_id", nargs="?", default=DEFAULT_SCENARIO_ID)
    parser.add_argument("--model", default=None, help="Overrides OPENROUTER_MODEL for intent_grounding_node")
    parser.add_argument("--prompt-strategy", default="zero_shot", choices=["zero_shot", "one_shot", "few_shot"])
    parser.add_argument(
        "--explanation-model", default=None,
        help="Overrides the model for explanation_node independently (defaults to --model if not given)",
    )
    args = parser.parse_args()
    record = run(
        args.scenario_id, model=args.model, prompt_strategy=args.prompt_strategy,
        explanation_model=args.explanation_model, verbose=True,
    )
    print("\n=== full record (JSON) ===")
    print(json.dumps(record, indent=2, ensure_ascii=False))
