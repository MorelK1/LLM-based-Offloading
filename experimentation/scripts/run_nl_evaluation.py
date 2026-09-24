"""Stage 1 of the NL evaluation pipeline: run the 34 hand-authored NL cases
(data/eval/intent_grounding_enact_extended.jsonl + ..._clarity_spectrum.jsonl)
3x each through the REAL pipeline (intent_grounding_node -> necessity_checker_node
-> decision_engine_node), and persist every observation, unscored, to
experimentation/data/nl_evaluation_raw.jsonl.

This is the only stage that calls the LLM. Re-run it only when you actually want
fresh model output (new prompt, new model, ...) -- scoring/analysis (stages 2/3)
never need to touch it again once this file exists.

Run from the project root:
    PYTHONPATH=src venv/bin/python3 experimentation/scripts/run_nl_evaluation.py
"""

import json
import time
from pathlib import Path

from agent.model.schemas import Requirement
from agent.nodes.decision_engine import decision_engine_node
from agent.nodes.intent_grounding import intent_grounding_node
from agent.nodes.necessity_checker import necessity_checker_node
from agent.utils.data_loader import load_links, load_nodes, load_services

NODES_CSV = "data/enact_scenario/nodes.csv"
LINKS_CSV = "data/enact_scenario/links.csv"
SERVICES_JSON = "data/enact_scenario/services_pipeline.json"

SOURCES = [
    ("data/eval/intent_grounding_enact_extended.jsonl", "extended"),
    ("data/eval/intent_grounding_enact_clarity_spectrum.jsonl", "clarity_spectrum"),
]

OUT_PATH = Path("experimentation/data/nl_evaluation_raw.jsonl")
RUNS_PER_CASE = 3


def load_cases() -> list[dict]:
    cases = []
    for path, source in SOURCES:
        with open(path) as f:
            for line in f:
                case = json.loads(line)
                case["dataset_source"] = source
                case.setdefault("clarity_tier", None)
                cases.append(case)
    return cases


def requirement_to_dict(r: Requirement) -> dict:
    return {
        "service": r.service, "kpi_type": r.kpi_type, "comparator": r.comparator,
        "target_value": r.target_value, "unit": r.unit, "source_span": r.source_span,
    }


def main() -> None:
    nodes = load_nodes(NODES_CSV)
    links = load_links(LINKS_CSV)
    services = load_services(SERVICES_JSON)
    cases = load_cases()

    total = len(cases) * RUNS_PER_CASE
    print(f"Running {len(cases)} cases x {RUNS_PER_CASE} runs = {total} real LLM calls...\n")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    n_done = 0
    with open(OUT_PATH, "w") as out:
        for case in cases:
            for run_idx in range(1, RUNS_PER_CASE + 1):
                t0 = time.time()
                gstate = {"intent_text": case["intent_text"], "services": services}
                extracted = intent_grounding_node(gstate)["requirements"]

                nstate = {"services": services, "nodes": nodes, "links": links, "requirements": extracted}
                nres = necessity_checker_node(nstate)["necessity_result"]

                decision: dict | str = {}
                if nres.status == "reconfiguration_required":
                    try:
                        dres = decision_engine_node(nstate)["decision_result"]
                        decision = dres.decision
                    except ValueError:
                        decision = "NO_VALID_PLACEMENT"

                elapsed = time.time() - t0
                row = {
                    "id": case["id"],
                    "dataset_source": case["dataset_source"],
                    "clarity_tier": case["clarity_tier"],
                    "run": run_idx,
                    "intent_text": case["intent_text"],
                    "expected_requirements": case["expected_requirements"],
                    "extracted_requirements": [requirement_to_dict(r) for r in extracted],
                    "necessity_status": nres.status,
                    "necessity_violated": nres.violated_requirements,
                    "decision": decision,
                    "elapsed_s": round(elapsed, 2),
                }
                out.write(json.dumps(row) + "\n")
                out.flush()

                n_done += 1
                print(f"[{n_done}/{total}] {case['id']} (run {run_idx}) -> "
                      f"{len(extracted)} extracted, status={nres.status} ({elapsed:.1f}s)")

    print(f"\nWrote {n_done} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
