"""Runs ONE public_safety e2e_v2 sample through the REAL, FULL graph
(intent_grounding -> necessity_checker -> decision_engine (if needed) ->
explanation), real LLM calls included -- unlike run_sample.py, which
bypasses extraction by injecting ground_truth.structured_requirement
directly.

Persists a COMPLETE raw record per sample (not just a verdict) -- every
field of every extracted requirement (not only the first, not only a diff
on mismatch), the full expected structured_requirement and reconfiguration
ground truth, dataset dimensions (intent.style/source, change_type), and
per-call timing/token usage. No metric (F1, Exact Match, Jaccard, cost...)
is computed here -- this only captures what such metrics will need, so
they can be computed later from the file without re-running anything (real
LLM calls are expensive and rate-limited -- see run_batch_full_graph.py).

model/prompt_strategy/explanation_model let experimentation scripts vary
which LLM and which prompting strategy intent_grounding_node uses, and
independently which model explanation_node uses, without touching src/ --
see graph.py:build_graph.

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/run_sample_full_graph.py PS-E2E-0001
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.graph import build_graph  # noqa: E402
from loader import load_links, load_nodes, load_sample, load_services_and_flows  # noqa: E402

_REQ_FIELDS = ("target_type", "target_id", "kpi_type", "comparator", "target_value", "unit", "source_span")

# Maps (necessity_result.status, decision_result.outcome | None) onto
# public_safety's own outcome vocabulary (STAY/OFFLOAD/INFEASIBLE).
_OUTCOME_MAP = {
    ("no_action_needed", None): "STAY",
    ("reconfiguration_required", "FEASIBLE"): "OFFLOAD",
    ("reconfiguration_required", "INFEASIBLE"): "INFEASIBLE",
}


def build_record(sample: dict, state_result: dict, run_config: dict) -> dict:
    """Everything a later scoring pass could need -- see module docstring."""
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
        "explanation_text": state_result["explanation"],
        "extraction_model": state_result.get("extraction_model"),
        "extraction_elapsed_s": state_result.get("extraction_elapsed_s"),
        "extraction_token_usage": state_result.get("extraction_token_usage"),
        "extraction_parsing_error": state_result.get("extraction_parsing_error"),
        "explanation_model": state_result.get("explanation_model"),
        "explanation_elapsed_s": state_result.get("explanation_elapsed_s"),
        "explanation_token_usage": state_result.get("explanation_token_usage"),
    }


def run(
    sample_id: str,
    graph=None,
    model: str | None = None,
    prompt_strategy: str = "zero_shot",
    explanation_model: str | None = None,
    verbose: bool = True,
) -> dict:
    """Returns the full persisted record (see build_record) -- the caller
    decides whether/where to write it (run_batch_full_graph.py appends it to
    a JSONL file; this module's __main__ just prints it)."""
    graph = graph or build_graph(
        model=model, prompt_strategy=prompt_strategy, explanation_model=explanation_model
    )
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

    run_config = {
        "model": model, "prompt_strategy": prompt_strategy,
        "explanation_model": explanation_model if explanation_model is not None else model,
    }
    record = build_record(sample, result, run_config)

    if verbose:
        exp = record["expected"]
        extracted_summary = record["extracted_requirements"] or "(none)"
        print(f"{sample_id}: {record['intent_text']!r} [style={record['intent_style']}]")
        print(f"  expected: {exp['target_type']}:{exp['target_id']} {exp['kpi_type']} "
              f"{exp['comparator']} {exp['target_value']}{exp['unit']} -> {exp['outcome']}")
        print(f"  extracted: {extracted_summary}")
        print(f"  decision: {record['our_outcome']} (expected {exp['outcome']}) "
              f"-- {'MATCH' if record['our_outcome'] == exp['outcome'] else 'MISMATCH'}")
        if record["decision_moved"]:
            print(f"  moved: {record['decision_moved']}")
        print(f"  models: extraction={record['extraction_model']} explanation={record['explanation_model']}")
        print(f"  timing: extraction={record['extraction_elapsed_s']:.2f}s "
              f"explanation={record['explanation_elapsed_s']:.2f}s")
        print(f"  tokens: extraction={record['extraction_token_usage']} "
              f"explanation={record['explanation_token_usage']}")
        print(f"  explanation: {record['explanation_text']}")

    return record


if __name__ == "__main__":
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "PS-E2E-0001"
    run(sample_id)
