"""Runs ONE public_safety e2e_v2 sample through a REAL, compiled graph --
intent_grounding -> necessity_checker -> decision_engine (if needed) -- but
skipping explanation_node entirely (graph.py:build_graph(include_explanation=False)).

Unlike run_sample.py (bypasses extraction, ground truth injected), this
still uses the real LLM for extraction. Unlike run_sample_full_graph.py
(all 4 nodes), it never calls explanation_node: that node is a pure
epilogue that never feeds back into the decision (confirmed structurally),
so skipping it changes nothing about what's measured here (extraction +
decision correctness) while roughly halving the LLM cost per sample (one
call instead of two).

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/run_sample_no_explanation.py PS-E2E-0001
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.graph import build_graph  # noqa: E402
from loader import load_links, load_nodes, load_sample, load_services_and_flows  # noqa: E402

_REQ_FIELDS = ("target_type", "target_id", "kpi_type", "comparator", "target_value", "unit", "source_span")

_OUTCOME_MAP = {
    ("no_action_needed", None): "STAY",
    ("reconfiguration_required", "FEASIBLE"): "OFFLOAD",
    ("reconfiguration_required", "INFEASIBLE"): "INFEASIBLE",
}


def build_record(sample: dict, state_result: dict, run_config: dict) -> dict:
    gt = sample["ground_truth"]
    sr = gt["structured_requirement"]
    recon = gt["reconfiguration"]

    nres = state_result["necessity_result"]
    dres = state_result["decision_result"]
    decision_outcome = dres.outcome if dres else None
    our_outcome = _OUTCOME_MAP.get(
        (nres.status, decision_outcome), f"UNKNOWN({nres.status},{decision_outcome})"
    )

    return {
        "run_config": run_config,
        "sample_id": sample["sample_id"],
        "technical_change_id": sample["technical_change_id"],
        "intent_text": sample["intent"]["text"],
        "intent_style": sample["intent"]["style"],
        "intent_source": sample["intent"]["source"],
        "change_type": sample["metadata"]["change_type"],
        "infrastructure_id": sample["infrastructure_id"],
        "application_context_id": sample["application_context_id"],
        "expected": {
            "target_type": sr["target_type"], "target_id": sr["target"],
            "kpi_type": sr["kpi_type"], "comparator": sr["comparator"],
            "target_value": sr["target_value"], "unit": sr["unit"],
            "outcome": gt["outcome"],
            "minimum_moves": recon.get("minimum_moves"),
            "reference_moved_services": recon.get("reference_moved_services"),
        },
        "extracted_requirements": [
            {f: getattr(r, f) for f in _REQ_FIELDS} for r in state_result["requirements"]
        ],
        "necessity_status": nres.status,
        "necessity_violated_requirements": nres.violated_requirements,
        "decision_outcome": decision_outcome,
        "decision_moved": sorted(dres.decision.keys()) if dres else None,
        "our_outcome": our_outcome,
        "extraction_elapsed_s": state_result.get("extraction_elapsed_s"),
        "extraction_token_usage": state_result.get("extraction_token_usage"),
        "extraction_parsing_error": state_result.get("extraction_parsing_error"),
        # No explanation_node in this graph -- these stay None, not omitted,
        # so a scoring pass over mixed full-graph/no-explanation JSONL files
        # can tell the two apart from the same field shape.
        "explanation_text": None,
        "explanation_elapsed_s": None,
        "explanation_token_usage": None,
    }


def run(
    sample_id: str,
    graph=None,
    model: str | None = None,
    prompt_strategy: str = "zero_shot",
    verbose: bool = True,
) -> dict:
    graph = graph or build_graph(model=model, prompt_strategy=prompt_strategy, include_explanation=False)
    sample = load_sample(sample_id)
    initial_placement = sample["ground_truth"]["reconfiguration"]["initial_placement"]

    nodes = load_nodes(sample["infrastructure_id"])
    links = load_links(sample["infrastructure_id"])
    services, flows = load_services_and_flows(sample["application_context_id"], initial_placement)

    state = {
        "intent_text": sample["intent"]["text"],
        "services": services, "flows": flows, "nodes": nodes, "links": links,
        "requirements": [], "necessity_result": None, "decision_result": None, "explanation": None,
    }
    result = graph.invoke(state)

    run_config = {"model": model, "prompt_strategy": prompt_strategy, "include_explanation": False}
    record = build_record(sample, result, run_config)

    if verbose:
        exp = record["expected"]
        extracted_summary = record["extracted_requirements"] or "(none)"
        print(f"{sample_id}: {record['intent_text']!r} [style={record['intent_style']}]")
        print(f"  expected: {exp['target_type']}:{exp['target_id']} {exp['kpi_type']} "
              f"{exp['comparator']} {exp['target_value']}{exp['unit']} -> {exp['outcome']}")
        print(f"  extracted: {extracted_summary}")
        print(f"  decision: {record['our_outcome']} (expected {exp['outcome']}) -- "
              f"{'MATCH' if record['our_outcome'] == exp['outcome'] else 'MISMATCH'}")
        if record["decision_moved"]:
            print(f"  moved: {record['decision_moved']}")
        print(f"  timing: extraction={record['extraction_elapsed_s']:.2f}s (no explanation call)")
        print(f"  tokens: extraction={record['extraction_token_usage']}")

    return record


if __name__ == "__main__":
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "PS-E2E-0001"
    run(sample_id)
