"""Decision-layer evaluation: the same method as RESULTS.md Part 2 / Part 4
(scripts/run_enact_scenario_checks.py), formalized as a reusable, persisted
experiment -- the LLM is bypassed entirely, expected_requirements is injected
directly as ground truth into necessity_checker_node / decision_engine_node.

Unlike experimentation/scripts/run_nl_evaluation.py, this is fully
deterministic (no LLM call at all) -- running the same case twice always
produces the same output, so each case is run ONCE, not 3x.

Scope: the 10 original cases (data/eval/intent_grounding_enact.jsonl) + the 14
`extended` cases (data/eval/intent_grounding_enact_extended.jsonl) -- the same
24 cases already covered qualitatively in RESULTS.md. `clarity_spectrum` is
deliberately NOT included here: those 20 cases were designed to test
extraction under varying clarity, not to carry a designed
violated/satisfied ground truth, so there is nothing honest to score them
against at the decision layer.

`expected_necessity_status` is derived from the existing `"violated"` tag
(present on exactly the cases that were deliberately designed to violate their
own requirement -- enact-103/108/110/112/113/114) rather than duplicated into
a new field -- no source file is modified.

Run from the project root:
    PYTHONPATH=src venv/bin/python3 experimentation/scripts/run_decision_evaluation.py
"""

import json
from pathlib import Path

from agent.model.schemas import Requirement
from agent.nodes.decision_engine import decision_engine_node
from agent.nodes.necessity_checker import necessity_checker_node
from agent.utils.data_loader import load_links, load_nodes, load_services

NODES_CSV = "data/enact_scenario/nodes.csv"
LINKS_CSV = "data/enact_scenario/links.csv"
SERVICES_JSON = "data/enact_scenario/services_pipeline.json"

SOURCES = [
    ("data/eval/intent_grounding_enact.jsonl", "original"),
    ("data/eval/intent_grounding_enact_extended.jsonl", "extended"),
]

OUT_PATH = Path("experimentation/data/decision_evaluation_raw.jsonl")


def load_cases() -> list[dict]:
    cases = []
    for path, source in SOURCES:
        with open(path) as f:
            for line in f:
                case = json.loads(line)
                case["dataset_source"] = source
                case["expected_necessity_status"] = (
                    "reconfiguration_required" if "violated" in case.get("tags", [])
                    else "no_action_needed"
                )
                cases.append(case)
    return cases


def main() -> None:
    nodes = load_nodes(NODES_CSV)
    links = load_links(LINKS_CSV)
    services = load_services(SERVICES_JSON)
    cases = load_cases()

    print(f"Running {len(cases)} cases (1 run each, deterministic, LLM bypassed)...\n")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as out:
        for i, case in enumerate(cases, start=1):
            requirements = [
                Requirement(**r, source_span="ground_truth", requirement_id=f"req-{j:03d}")
                for j, r in enumerate(case["expected_requirements"])
            ]

            state = {"services": services, "nodes": nodes, "links": links, "requirements": requirements}
            nres = necessity_checker_node(state)["necessity_result"]

            decision: dict | str = {}
            if nres.status == "reconfiguration_required":
                try:
                    dres = decision_engine_node(state)["decision_result"]
                    decision = dres.decision
                except ValueError:
                    decision = "NO_VALID_PLACEMENT"

            row = {
                "id": case["id"],
                "dataset_source": case["dataset_source"],
                "tags": case.get("tags", []),
                "expected_requirements": case["expected_requirements"],
                "expected_necessity_status": case["expected_necessity_status"],
                "necessity_status": nres.status,
                "necessity_violated": nres.violated_requirements,
                "decision": decision,
            }
            out.write(json.dumps(row) + "\n")
            print(f"[{i}/{len(cases)}] {case['id']}: expected={case['expected_necessity_status']} "
                  f"observed={nres.status} decision={decision}")

    print(f"\nWrote {len(cases)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
