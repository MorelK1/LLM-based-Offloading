"""Runs a BATCH of eval/experiment_150 scenarios through the REAL, FULL graph
and appends one complete raw record per scenario (see
run_sample_full_graph.py:run) to a JSONL file as it goes -- written
incrementally, not buffered, so a crash or a rate-limit partway through
doesn't lose what already ran. No metric is computed here -- a later,
separate scoring script compares each record's prediction against its
ground_truth (also captured in the record).

scenarios.json is already interleaved across outcomes (confirmed: the first
20 scenarios split STAY/OFFLOAD/INFEASIBLE close to the full dataset's own
ratio), so scenarios[:n] is a representative subset -- no stratified-subset
file needed here, unlike public_safety's e2e_samples.json.

Rate-limit handling copied from
expérimentations/public_safety/run_batch_full_graph.py (pure
OpenRouter/network concern, unrelated to which dataset is being run).

model/explanation_model/prompt_strategy are left unset by default (None),
resolved to OPENROUTER_MODEL (.env) -- pass --model (and optionally
--explanation-model) to pick a specific OpenRouter model without touching
this file.

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 eval/run_batch_full_graph.py \\
        [N] [--delay SECONDS] [--model MODEL] [--prompt-strategy STRATEGY] [--explanation-model MODEL]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "system_model"))

import openai  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from run_sample_full_graph import run  # noqa: E402

DEFAULT_N = 10
DEFAULT_DELAY_S = 5.0
MAX_RETRIES_ON_RATE_LIMIT = 3
DEFAULT_RETRY_WAIT_S = 120.0  # OpenRouter's own Retry-After hint, observed
RESULTS_DIR = Path(__file__).parent / "results"
SCENARIOS_PATH = Path(__file__).parent / "experiment_150" / "scenarios.json"


def _retry_info(exc: Exception) -> tuple[str, float] | None:
    """Returns (reason, wait_s) for a known RETRYABLE rate-limit shape, or
    None if exc isn't one we know how to recover from (caller fails fast).
    See expérimentations/public_safety/run_batch_full_graph.py for the full
    rationale behind each shape -- copied verbatim, this is a pure
    OpenRouter/network concern, unrelated to which dataset is running."""
    if isinstance(exc, openai.APIConnectionError):  # not a subclass of APIStatusError -- separate branch
        return "connection_error", 15.0
    if not isinstance(exc, openai.APIStatusError):
        return None
    body = exc.body if isinstance(exc.body, dict) else {}
    metadata = body.get("error", {}).get("metadata", {})

    if exc.status_code == 402:
        if metadata.get("reason") != "in_flight_budget_exhausted":
            return None
        retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
        try:
            return "in_flight_budget_exhausted", float(retry_after)
        except (TypeError, ValueError):
            return "in_flight_budget_exhausted", DEFAULT_RETRY_WAIT_S

    if exc.status_code == 429:
        reset_ms = metadata.get("headers", {}).get("X-RateLimit-Reset")
        try:
            wait_s = max(0.0, float(reset_ms) / 1000 - time.time()) + 2.0  # +2s buffer past the reset instant
        except (TypeError, ValueError):
            wait_s = DEFAULT_RETRY_WAIT_S
        return "rate_limit_rpm", wait_s

    return None


def run_with_retry(scenario_id: str, graph, **run_kwargs) -> dict | None:
    """Returns the full record on success, or None on a non-retryable/
    exhausted-retries failure (the caller logs an error record for it)."""
    for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
        try:
            return run(scenario_id, graph=graph, verbose=True, **run_kwargs)
        except Exception as exc:  # noqa: BLE001 -- only a retryable rate-limit loops, anything else is fatal per-scenario
            info = _retry_info(exc)
            if info and attempt < MAX_RETRIES_ON_RATE_LIMIT:
                reason, wait_s = info
                print(f"{scenario_id}: rate-limited ({reason}), "
                      f"attempt {attempt}/{MAX_RETRIES_ON_RATE_LIMIT}, waiting {wait_s:.0f}s before retrying...")
                time.sleep(wait_s)
                continue
            if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
                body = exc.body if isinstance(exc.body, dict) else {}
                if body.get("error", {}).get("metadata", {}).get("reason") == "weight_exceeds_budget":
                    print(f"{scenario_id}: ERROR -- OpenRouter account out of credits "
                          f"(weight_exceeds_budget) -- not retrying, add credits to proceed.")
                    return None
            print(f"{scenario_id}: ERROR -- {exc}")
            return None


def main(
    limit: int, delay_s: float, model: str | None, prompt_strategy: str, explanation_model: str | None,
) -> None:
    with open(SCENARIOS_PATH) as f:
        all_scenarios = json.load(f)
    scenario_ids = [s["id"] for s in all_scenarios[:limit]]

    graph = build_graph(
        model=model, prompt_strategy=prompt_strategy, explanation_model=explanation_model
    )  # built once, reused

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    model_tag = (model or "default").replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{model_tag}__{prompt_strategy}__{timestamp}.jsonl"
    print(f"Writing results to {out_path}\n")

    n_ok = 0
    n_error = 0
    start = time.time()
    with open(out_path, "a") as out:
        for i, scenario_id in enumerate(scenario_ids, start=1):
            record = run_with_retry(
                scenario_id, graph,
                model=model, prompt_strategy=prompt_strategy, explanation_model=explanation_model,
            )
            if record is None:
                record = {
                    "run_config": {"model": model, "prompt_strategy": prompt_strategy,
                                   "explanation_model": explanation_model},
                    "scenario_id": scenario_id, "error": "see console log above",
                }
                n_error += 1
            else:
                n_ok += 1
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            print(f"[{i}/{len(scenario_ids)}] done ({time.time() - start:.0f}s elapsed)\n")
            if i < len(scenario_ids) and delay_s > 0:
                time.sleep(delay_s)

    print(f"=== {n_ok} ok, {n_error} errors, written to {out_path} ===")
    print("No metric computed here -- score later from the ground_truth field already in each record.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("n", nargs="?", type=int, default=DEFAULT_N)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_S,
                         help="Seconds to wait between scenarios (default: %(default)s)")
    parser.add_argument("--model", default=None,
                         help="Overrides OPENROUTER_MODEL for intent_grounding_node")
    parser.add_argument("--prompt-strategy", default="zero_shot",
                         choices=["zero_shot", "one_shot", "few_shot"])
    parser.add_argument("--explanation-model", default=None,
                         help="Overrides the model for explanation_node independently "
                              "(defaults to --model if not given)")
    args = parser.parse_args()
    main(args.n, args.delay, args.model, args.prompt_strategy, args.explanation_model)
