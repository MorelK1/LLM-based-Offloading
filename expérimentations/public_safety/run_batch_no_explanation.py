"""Runs a BATCH of public_safety e2e_v2 samples through the real graph
(intent_grounding -> necessity_checker -> decision_engine), skipping
explanation_node -- see run_sample_no_explanation.py. Roughly half the LLM
cost of run_batch_full_graph.py for the same extraction/decision signal.

Same incremental JSONL persistence and 402 retry/fail-fast handling as the
other batch scripts.

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/run_batch_no_explanation.py \\
        [N] [--delay SECONDS] [--model MODEL] [--prompt-strategy STRATEGY]
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
from run_sample_no_explanation import run  # noqa: E402

DEFAULT_N = 10
DEFAULT_DELAY_S = 5.0
MAX_RETRIES_ON_RATE_LIMIT = 3
DEFAULT_RETRY_WAIT_S = 120.0
RESULTS_DIR = Path(__file__).parent / "results"


def _error_reason(exc: Exception) -> str | None:
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


def run_with_retry(sample_id: str, graph, model: str | None, prompt_strategy: str) -> dict | None:
    for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
        try:
            return run(sample_id, graph=graph, model=model, prompt_strategy=prompt_strategy, verbose=True)
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


def main(limit: int, delay_s: float, model: str | None, prompt_strategy: str) -> None:
    samples = _read("e2e_samples.json")["samples"][:limit]
    graph = build_graph(model=model, prompt_strategy=prompt_strategy, include_explanation=False)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    model_tag = (model or "default").replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{model_tag}__{prompt_strategy}__no-explanation__{timestamp}.jsonl"
    print(f"Writing results to {out_path}\n")

    n_ok = 0
    n_error = 0
    start = time.time()
    with open(out_path, "a") as out:
        for i, sample in enumerate(samples, start=1):
            record = run_with_retry(sample["sample_id"], graph, model, prompt_strategy)
            if record is None:
                record = {
                    "run_config": {"model": model, "prompt_strategy": prompt_strategy, "include_explanation": False},
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
    args = parser.parse_args()
    main(args.n, args.delay, args.model, args.prompt_strategy)
