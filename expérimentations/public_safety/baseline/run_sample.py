"""Runs ONE public_safety e2e_v2 sample through the single-LLM baseline and
builds a complete raw record -- extraction correctness (vs ground truth
structured_requirement), outcome correctness (STAY/OFFLOAD/INFEASIBLE vs
ground truth), AND independent placement feasibility (is the LLM's own
proposed new_placement actually valid under our real capacity/latency/
connectivity checks -- see verifier.py). No metric is computed/aggregated
here, only captured, same principle as run_sample_full_graph.py.

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/baseline/run_sample.py PS-E2E-0001
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for loader.py
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for prompt.py/runner.py/verifier.py

from loader import load_links, load_nodes, load_sample, load_services_and_flows  # noqa: E402
from prompt import DEFAULT_PROMPT_STRATEGY  # noqa: E402
from runner import run_baseline  # noqa: E402
from verifier import requirements_from_baseline, verify_placement  # noqa: E402

_REQ_FIELDS = ("target_type", "target_id", "kpi_type", "comparator", "target_value", "unit")


def build_record(sample: dict, services: dict, outcome: dict, run_config: dict) -> dict:
    gt = sample["ground_truth"]
    sr = gt["structured_requirement"]
    recon = gt["reconfiguration"]
    expected = {
        "target_type": sr["target_type"], "target_id": sr["target"],
        "kpi_type": sr["kpi_type"], "comparator": sr["comparator"],
        "target_value": sr["target_value"], "unit": sr["unit"],
        "outcome": gt["outcome"],
        "minimum_moves": recon.get("minimum_moves"),
        "reference_moved_services": recon.get("reference_moved_services"),
    }

    result = outcome["result"]
    record = {
        "run_config": run_config,
        "sample_id": sample["sample_id"],
        "technical_change_id": sample["technical_change_id"],
        "intent_text": sample["intent"]["text"],
        "intent_style": sample["intent"]["style"],
        "intent_source": sample["intent"]["source"],
        "change_type": sample["metadata"]["change_type"],
        "infrastructure_id": sample["infrastructure_id"],
        "application_context_id": sample["application_context_id"],
        "expected": expected,
        "model": outcome["model"],
        "elapsed_s": outcome["elapsed_s"],
        "token_usage": outcome["token_usage"],
        "parsing_error": outcome["parsing_error"],
    }

    if result is None:
        record.update({
            "extracted": None, "outcome": None, "proposed_placement": None,
            "placement_well_formed": None, "placement_feasible": None,
            "placement_checks": None, "explanation_text": None,
        })
        return record

    # A compound intent yields more than one entry here -- ground truth
    # (expected, above) is still a single structured_requirement per
    # public_safety sample, so scoring code (not written yet) decides later
    # how to compare a list against a single expected entry; this just
    # captures everything the model actually extracted, faithfully.
    extracted = [{f: getattr(r, f) for f in _REQ_FIELDS} for r in result.requirements]
    placement_well_formed = set(result.new_placement.keys()) == set(services.keys())
    # Backfill any service the LLM omitted with its current_node -- an
    # incomplete placement is a formatting problem, not a reason to skip
    # verifying what WAS given (see verifier.py's docstring).
    full_placement = {sid: result.new_placement.get(sid, s.current_node) for sid, s in services.items()}

    record.update({
        "extracted": extracted,
        "outcome": result.outcome,
        "proposed_placement": result.new_placement,
        "placement_well_formed": placement_well_formed,
        "explanation_text": result.explanation,
    })
    return record, full_placement


def run(
    sample_id: str,
    model: str | None = None,
    prompt_strategy: str = DEFAULT_PROMPT_STRATEGY,
    verbose: bool = True,
) -> dict:
    sample = load_sample(sample_id)
    initial_placement = sample["ground_truth"]["reconfiguration"]["initial_placement"]

    nodes = load_nodes(sample["infrastructure_id"])
    links = load_links(sample["infrastructure_id"])
    services, flows = load_services_and_flows(sample["application_context_id"], initial_placement)

    outcome = run_baseline(
        sample["intent"]["text"], services, flows, nodes, links,
        model=model, prompt_strategy=prompt_strategy,
    )
    run_config = {"model": model, "prompt_strategy": prompt_strategy}

    built = build_record(sample, services, outcome, run_config)
    if isinstance(built, tuple):
        record, full_placement = built
        requirements = requirements_from_baseline(outcome["result"])
        feasible, checks = verify_placement(nodes, services, flows, links, requirements, full_placement)
        record["placement_feasible"] = feasible
        record["placement_checks"] = [f"{'ok' if ok else 'FAIL'}: {reason}" for ok, reason in checks]
    else:
        record = built

    if verbose:
        exp = record["expected"]
        print(f"{sample_id}: {record['intent_text']!r} [style={record['intent_style']}]")
        print(f"  expected: {exp['target_type']}:{exp['target_id']} {exp['kpi_type']} "
              f"{exp['comparator']} {exp['target_value']}{exp['unit']} -> {exp['outcome']}")
        if record["extracted"] is None:
            print(f"  PARSING FAILED -- {record['parsing_error']}")
        else:
            print(f"  extracted: {record['extracted']}")
            print(f"  outcome: {record['outcome']} (expected {exp['outcome']}) -- "
                  f"{'MATCH' if record['outcome'] == exp['outcome'] else 'MISMATCH'}")
            print(f"  placement_well_formed={record['placement_well_formed']} "
                  f"placement_feasible={record['placement_feasible']}")
        print(f"  elapsed={record['elapsed_s']:.2f}s tokens={record['token_usage']}")

    return record


if __name__ == "__main__":
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "PS-E2E-0001"
    run(sample_id)
