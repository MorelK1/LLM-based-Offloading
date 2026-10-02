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


def _retry_info(exc: Exception) -> tuple[str, float] | None:
    """Returns (reason, wait_s) for a known RETRYABLE rate-limit shape, or
    None if exc isn't one we know how to recover from (caller fails fast).

    Two unrelated shapes observed in practice, both status-coded differently
    from a genuine, non-retryable error:
    - 402 in_flight_budget_exhausted: too many concurrent in-flight requests
      -- waits for OpenRouter's own Retry-After hint.
    - 429 new-account-rpm: a hard per-minute request cap tied to account age
      (observed: 20 req/min for openai/gpt-5.4-mini, independent of credits
      or --delay spacing when --delay is too low to stay under it) -- waits
      until the window resets, per X-RateLimit-Reset (epoch ms).
    402 weight_exceeds_budget (out of credits) is deliberately NOT retryable
    here -- confirmed: retrying it twice (240s) before giving up, when it
    needed credits added, not a wait.

    A third, different shape: openai.APIConnectionError ("Connection
    error.") -- a generic transient network failure (observed isolated,
    non-recurring instances across several models/providers during a live
    run), not status-coded at all since the request never got a response.
    Short fixed wait, since there's no server-provided hint for how long to
    back off."""
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


def run_with_retry(sample_id: str, graph, **run_kwargs) -> dict | None:
    """Returns the full record on success, or None on a non-retryable/
    exhausted-retries failure (the caller logs an error record for it)."""
    for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
        try:
            return run(sample_id, graph=graph, verbose=True, **run_kwargs)
        except Exception as exc:  # noqa: BLE001 -- only a retryable rate-limit loops, anything else is fatal per-sample
            info = _retry_info(exc)
            if info and attempt < MAX_RETRIES_ON_RATE_LIMIT:
                reason, wait_s = info
                print(f"{sample_id}: rate-limited ({reason}), "
                      f"attempt {attempt}/{MAX_RETRIES_ON_RATE_LIMIT}, waiting {wait_s:.0f}s before retrying...")
                time.sleep(wait_s)
                continue
            if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
                body = exc.body if isinstance(exc.body, dict) else {}
                if body.get("error", {}).get("metadata", {}).get("reason") == "weight_exceeds_budget":
                    print(f"{sample_id}: ERROR -- OpenRouter account out of credits "
                          f"(weight_exceeds_budget) -- not retrying, add credits to proceed.")
                    return None
            print(f"{sample_id}: ERROR -- {exc}")
            return None


def main(
    limit: int, delay_s: float, model: str | None, prompt_strategy: str,
    explanation_model: str | None, sample_ids_file: str | None,
) -> None:
    all_samples = _read("e2e_samples.json")["samples"]
    if sample_ids_file:
        # Fixed, reproducible subset (e.g. sample_subset_450.json) -- NOT a
        # prefix of e2e_samples.json, which is grouped by outcome (all 41
        # INFEASIBLE samples come first), so samples[:limit] would silently
        # skew small/medium limits toward one outcome type. Also lets the
        # baseline runs reuse the exact same sample_ids for a fair
        # side-by-side comparison.
        with open(sample_ids_file) as f:
            wanted_ids = json.load(f)["sample_ids"]
        by_id = {s["sample_id"]: s for s in all_samples}
        samples = [by_id[sid] for sid in wanted_ids if sid in by_id][:limit]
    else:
        samples = all_samples[:limit]
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
    parser.add_argument("--sample-ids-file", default=None,
                         help="JSON file with a {'sample_ids': [...]} fixed subset to run "
                              "(e.g. sample_subset_450.json) instead of the first N samples "
                              "in e2e_samples.json, which is grouped by outcome")
    args = parser.parse_args()
    main(args.n, args.delay, args.model, args.prompt_strategy, args.explanation_model, args.sample_ids_file)
