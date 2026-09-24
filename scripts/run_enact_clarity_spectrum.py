"""Run the REAL intent_grounding_node (LLM extraction, OpenRouter) 3x on each of
the 20 data/eval/intent_grounding_enact_clarity_spectrum.jsonl scenarios, then
feed whatever gets extracted into the REAL necessity_checker_node and
decision_engine_node. Unlike scripts/run_enact_scenario_checks.py (which
bypasses the LLM and feeds ground truth directly), this exercises the full
intent -> requirement -> decision path exactly as the graph would.

Not part of the runtime pipeline -- a one-off evaluation script.
"""

import json
import time

from agent.model.schemas import Requirement
from agent.nodes.decision_engine import decision_engine_node
from agent.nodes.intent_grounding import intent_grounding_node
from agent.nodes.necessity_checker import necessity_checker_node
from agent.utils.data_loader import load_links, load_nodes, load_services

NODES_CSV = "data/enact_scenario/nodes.csv"
LINKS_CSV = "data/enact_scenario/links.csv"
SERVICES_JSON = "data/enact_scenario/services_pipeline.json"
CASES_JSONL = "data/eval/intent_grounding_enact_clarity_spectrum.jsonl"
RUNS_PER_CASE = 3
TOLERANCE = 0.05  # relative tolerance on target_value when comparing to ground truth


def load_cases() -> list[dict]:
    with open(CASES_JSONL) as f:
        return [json.loads(line) for line in f]


def requirement_matches(extracted: Requirement, expected: dict) -> bool:
    if extracted.service != expected["service"]:
        return False
    if extracted.kpi_type != expected["kpi_type"]:
        return False
    if extracted.comparator != expected["comparator"]:
        return False
    if extracted.unit != expected["unit"]:
        return False
    target = expected["target_value"]
    tol = max(abs(target) * TOLERANCE, 1e-9)
    return abs(extracted.target_value - target) <= tol


def score_run(extracted: list[Requirement], expected_list: list[dict]) -> bool:
    if not expected_list:
        return len(extracted) == 0
    if len(extracted) != len(expected_list):
        return False
    return all(
        any(requirement_matches(e, exp) for e in extracted) for exp in expected_list
    )


def main() -> None:
    nodes = load_nodes(NODES_CSV)
    links = load_links(LINKS_CSV)
    services = load_services(SERVICES_JSON)
    cases = load_cases()

    results = []  # one row per (case, run)
    print(f"Running {len(cases)} scenarios x {RUNS_PER_CASE} runs = "
          f"{len(cases) * RUNS_PER_CASE} real LLM calls...\n")

    for case in cases:
        for run_idx in range(1, RUNS_PER_CASE + 1):
            t0 = time.time()
            gstate = {"intent_text": case["intent_text"], "services": services}
            extracted = intent_grounding_node(gstate)["requirements"]
            extraction_ok = score_run(extracted, case["expected_requirements"])

            nstate = {
                "services": services, "nodes": nodes, "links": links, "requirements": extracted,
            }
            nres = necessity_checker_node(nstate)["necessity_result"]
            decision = {}
            if nres.status == "reconfiguration_required":
                try:
                    dres = decision_engine_node(nstate)["decision_result"]
                    decision = dres.decision
                except ValueError:
                    # No node satisfies the (possibly ill-scaled, e.g. a tiny
                    # ceiling checked against every node's full raw capacity --
                    # see RESULTS.md sec. 8) requirement at all.
                    decision = "NO_VALID_PLACEMENT"

            elapsed = time.time() - t0
            row = {
                "id": case["id"], "tier": case["clarity_tier"], "run": run_idx,
                "extraction_ok": extraction_ok,
                "extracted": [(r.service, r.kpi_type, r.comparator, r.target_value, r.unit) for r in extracted],
                "expected": [(e["service"], e["kpi_type"], e["comparator"], e["target_value"], e["unit"])
                             for e in case["expected_requirements"]],
                "necessity_status": nres.status,
                "decision": decision,
                "elapsed_s": round(elapsed, 2),
            }
            results.append(row)
            flag = "OK" if extraction_ok else "MISS"
            print(f"[{case['id']} tier={case['clarity_tier']} run={run_idx}] {flag:<4} "
                  f"extracted={row['extracted']} status={nres.status} decision={decision} ({elapsed:.1f}s)")

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)

    per_tier: dict[int, list[bool]] = {}
    per_case: dict[str, list[bool]] = {}
    for r in results:
        per_tier.setdefault(r["tier"], []).append(r["extraction_ok"])
        per_case.setdefault(r["id"], []).append(r["extraction_ok"])

    print(f"\nOverall: {sum(r['extraction_ok'] for r in results)}/{len(results)} runs correct "
          f"({100 * sum(r['extraction_ok'] for r in results) / len(results):.0f}%)\n")

    print("Per clarity tier:")
    for tier in sorted(per_tier):
        oks = per_tier[tier]
        print(f"  tier {tier}: {sum(oks)}/{len(oks)} correct ({100 * sum(oks) / len(oks):.0f}%)")

    print("\nPer case (3/3, 2/3, 1/3, 0/3 correct across the 3 runs):")
    for case_id, oks in per_case.items():
        print(f"  {case_id}: {sum(oks)}/{len(oks)}")

    # Dump full results as JSON for the report to draw exact numbers from.
    with open("data/eval/enact_clarity_spectrum_run_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nFull results written to data/eval/enact_clarity_spectrum_run_results.json")


if __name__ == "__main__":
    main()
