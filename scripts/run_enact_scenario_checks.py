"""End-to-end checks for data/enact_scenario/: loads the scenario, runs every
data/eval/intent_grounding_enact*.jsonl case through the REAL necessity_checker
and decision_engine nodes (bypassing the LLM -- expected_requirements are fed
in directly as ground truth), and prints a plain-text report.

Not part of the runtime pipeline -- a one-off verification script, on the same
footing as scripts/generate_intent_dataset.py.
"""

import json
import time

from agent.model.schemas import ExtractedRequirement, Requirement
from agent.nodes.decision_engine import decision_engine_node
from agent.nodes.necessity_checker import necessity_checker_node
from agent.utils.data_loader import load_links, load_nodes, load_services

NODES_CSV = "data/enact_scenario/nodes.csv"
LINKS_CSV = "data/enact_scenario/links.csv"
SERVICES_JSON = "data/enact_scenario/services_pipeline.json"
ORIGINAL_CASES = "data/eval/intent_grounding_enact.jsonl"
EXTENDED_CASES = "data/eval/intent_grounding_enact_extended.jsonl"

OFFLOAD_CASE_IDS = ["enact-112", "enact-113", "enact-114"]


def load_cases(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> None:
    section("1. Loading data/enact_scenario/")
    nodes = load_nodes(NODES_CSV)
    links = load_links(LINKS_CSV)
    services = load_services(SERVICES_JSON)
    print(f"{len(nodes)} nodes  : {list(nodes)}")
    print(f"{len(links)} links")
    print(f"{len(services)} services: {list(services)}")

    section("2. Schema extension (energy/bandwidth KPI, W/Mbps units)")
    for kpi, unit in [("energy", "W"), ("bandwidth", "Mbps")]:
        r = ExtractedRequirement(
            kpi_type=kpi, comparator="lte", target_value=10, unit=unit,
            service="X", source_span="x",
        )
        print(f"OK  ExtractedRequirement(kpi_type={r.kpi_type!r}, unit={r.unit!r})")

    section("3. necessity_checker on every enact*.jsonl case (LLM bypassed, ground truth fed directly)")
    all_cases = load_cases(ORIGINAL_CASES) + load_cases(EXTENDED_CASES)
    reqs, case_by_id = [], {}
    for i, c in enumerate(all_cases):
        r = c["expected_requirements"][0]
        rid = f"req-{i:03d}"
        reqs.append(Requirement(**r, source_span="x", requirement_id=rid))
        case_by_id[rid] = c

    state = {"services": services, "nodes": nodes, "links": links, "requirements": reqs}
    nres = necessity_checker_node(state)["necessity_result"]

    mismatches = []
    print(f"{'id':<10} {'kpi':<10} {'cmp':<3} {'target':>8} {'unit':<5}  {'intended':<10} {'engine':<10}")
    for rid, c in case_by_id.items():
        r = c["expected_requirements"][0]
        intended = "violated" if "violated" in c.get("tags", []) else "satisfied"
        engine = "violated" if rid in nres.violated_requirements else "satisfied"
        flag = "" if intended == engine else "  <-- MISMATCH"
        if flag:
            mismatches.append(c["id"])
        print(f"{c['id']:<10} {r['kpi_type']:<10} {r['comparator']:<3} {r['target_value']:>8} "
              f"{r['unit']:<5}  {intended:<10} {engine:<10}{flag}")

    print(f"\n{len(mismatches)}/{len(all_cases)} cases mismatch intended vs. engine result: {mismatches}")
    print("Root cause: necessity_checker compares target_value directly to node.cpu_cores/"
          "node.ram_gb (raw static capacity, native units) -- no per-service usage accounting, "
          "no unit conversion. 'energy'/'bandwidth' requirements are silently skipped "
          "(kpi_type not in _KPI_TO_NODE_FIELD).")

    section("4. Offload scenarios: new/updated service vs. increased load on an existing service")
    for case_id in OFFLOAD_CASE_IDS:
        case = next(c for c in all_cases if c["id"] == case_id)
        r = case["expected_requirements"][0]
        req = Requirement(**r, source_span="x", requirement_id="req-offload")
        scenario_state = {"services": services, "nodes": nodes, "links": links, "requirements": [req]}

        nres = necessity_checker_node(scenario_state)["necessity_result"]
        t0 = time.time()
        dres = decision_engine_node(scenario_state)["decision_result"]
        elapsed = time.time() - t0

        print(f"\n[{case_id}] {case['intent_text']}")
        print(f"  requirement       : {r['service']} {r['kpi_type']} {r['comparator']} {r['target_value']} {r['unit']}")
        print(f"  necessity status  : {nres.status} (violated={nres.violated_requirements})")
        print(f"  decision (moved)  : {dres.decision}  [solved in {elapsed:.2f}s]")
        print(f"  full new config   : {dres.new_configuration}")


if __name__ == "__main__":
    main()
