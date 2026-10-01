"""Runs a BATCH of public_safety e2e_v2 samples through the REAL, FULL graph
and appends one complete raw record per sample (see
run_sample_full_graph.py:build_record) to a JSONL file as it goes --
written incrementally, not buffered, so a crash or a rate-limit partway
through doesn't lose what already ran. No metric is computed here -- this
only captures what a later, separate scoring script will need (F1, Exact
Match, Jaccard, cost/time comparisons across models/strategies...).

Expensive and slow compared to run_batch.py (decision-only, LLM bypassed):
~2 real LLM calls per sample, and OpenRouter's in-flight request budget
rejects calls fired too close together. --delay spaces samples out; on a
retryable 402 (in_flight_budget_exhausted) the sample is retried (respecting
Retry-After); a non-retryable 402 (weight_exceeds_budget -- account out of
credits) fails fast instead of wasting minutes retrying something waiting
can't fix.

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/run_batch_full_graph.py \\
        [N] [--delay SECONDS] [--model MODEL] [--prompt-strategy STRATEGY] [--explanation-model MODEL]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openai  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from loader import _read  # noqa: E402
from run_sample_full_graph import run  # noqa: E402

DEFAULT_N = 10
DEFAULT_DELAY_S = 5.0
MAX_RETRIES_ON_RATE_LIMIT = 3
DEFAULT_RETRY_WAIT_S = 120.0  # OpenRouter's own Retry-After hint, observed
RESULTS_DIR = Path(__file__).parent / "results"


def _error_reason(exc: Exception) -> str | None:
    """OpenRouter's 402 covers two unrelated situations, distinguished only
    by this field -- conflating them wastes minutes retrying something
    retrying can never fix (confirmed: retried "weight_exceeds_budget" twice,
    240s, before giving up -- it needed credits added, not a wait)."""
    if not (isinstance(exc, openai.APIStatusError) and exc.status_code == 402):
        return None
    body = exc.body if isinstance(exc.body, dict) else {}
    return body.get("error", {}).get("metadata", {}).get("reason")


def _retry_wait_seconds(exc: openai.APIStatusError) -> float:
    retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_WAIT_S


def run_with_retry(sample_id: str, graph, **run_kwargs) -> dict | None:
    """Returns the full record on success, or None on a non-retryable/
    exhausted-retries failure (the caller logs an error record for it)."""
    for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
        try:
            return run(sample_id, graph=graph, verbose=True, **run_kwargs)
        except Exception as exc:  # noqa: BLE001 -- only a retryable 402 loops, anything else is fatal per-sample
            reason = _error_reason(exc)
            if reason == "in_flight_budget_exhausted" and attempt < MAX_RETRIES_ON_RATE_LIMIT:
                wait_s = _retry_wait_seconds(exc)
                print(f"{sample_id}: rate-limited (402, in_flight_budget_exhausted), "
                      f"attempt {attempt}/{MAX_RETRIES_ON_RATE_LIMIT}, waiting {wait_s:.0f}s before retrying...")
                time.sleep(wait_s)
                continue
            if reason == "weight_exceeds_budget":
                print(f"{sample_id}: ERROR -- OpenRouter account out of credits "
                      f"(weight_exceeds_budget) -- not retrying, add credits to proceed.")
            else:
                print(f"{sample_id}: ERROR -- {exc}")
            return None


def main(
    limit: int, delay_s: float, model: str | None, prompt_strategy: str,
    explanation_model: str | None,
) -> None:
    samples = _read("e2e_samples.json")["samples"][:limit]
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
        for i, sample in enumerate(samples, start=1):
            record = run_with_retry(
                sample["sample_id"], graph,
                model=model, prompt_strategy=prompt_strategy, explanation_model=explanation_model,
            )
            if record is None:
                record = {
                    "run_config": {"model": model, "prompt_strategy": prompt_strategy,
                                   "explanation_model": explanation_model},
                    "sample_id": sample["sample_id"], "error": "see console log above",
                }
                n_error += 1
            else:
                n_ok += 1
            out.write(json.dumps(record) + "\n")
            out.flush()
            print(f"[{i}/{len(samples)}] done ({time.time() - start:.0f}s elapsed)\n")
            if i < len(samples) and delay_s > 0:
                time.sleep(delay_s)

    print(f"=== {n_ok} ok, {n_error} errors, written to {out_path} ===")
    print("No metric computed here -- see the module docstring for what to score from this file.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("n", nargs="?", type=int, default=DEFAULT_N)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_S,
                         help="Seconds to wait between samples (default: %(default)s)")
    parser.add_argument("--model", default=None,
                         help="Overrides OPENROUTER_MODEL for intent_grounding_node")
    parser.add_argument("--prompt-strategy", default="zero_shot",
                         choices=["zero_shot", "one_shot", "few_shot"])
    parser.add_argument("--explanation-model", default=None,
                         help="Overrides the model for explanation_node independently "
                              "(defaults to --model if not given)")
    args = parser.parse_args()
    main(args.n, args.delay, args.model, args.prompt_strategy, args.explanation_model)
