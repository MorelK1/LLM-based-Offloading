"""Runs every (or a subset of) public_safety e2e_v2 samples through the real
pipeline nodes and reports the match rate against ground truth, broken down
by change_type (RESOURCE/E2E) and expected outcome (STAY/OFFLOAD/INFEASIBLE).

Usage (from the project root):
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/run_batch.py [N]

N: number of samples to run (default: all 600). Samples are taken in file
order (not randomized), so a small N is a deterministic, reproducible subset.
"""

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loader import _read  # noqa: E402
from run_sample import run  # noqa: E402


def main(limit: int | None) -> None:
    samples = _read("e2e_samples.json")["samples"]
    if limit:
        samples = samples[:limit]

    results = []
    start = time.time()
    for i, sample in enumerate(samples, start=1):
        try:
            match = run(sample["sample_id"])
        except Exception as exc:  # noqa: BLE001 -- surfaced in the per-sample breakdown, not fatal
            print(f"{sample['sample_id']}: ERROR -- {exc}")
            match = False
        results.append({
            "sample_id": sample["sample_id"],
            "change_type": sample["metadata"]["change_type"],
            "expected_outcome": sample["ground_truth"]["outcome"],
            "match": match,
        })
        if i % 50 == 0:
            print(f"... {i}/{len(samples)} done ({time.time() - start:.0f}s elapsed)")

    elapsed = time.time() - start
    n = len(results)
    n_match = sum(r["match"] for r in results)
    print()
    print(f"=== Overall: {n_match}/{n} ({100 * n_match / n:.1f}%) matched, {elapsed:.0f}s ===")

    for change_type in ("RESOURCE", "E2E"):
        subset = [r for r in results if r["change_type"] == change_type]
        if not subset:
            continue
        n_sub_match = sum(r["match"] for r in subset)
        print(f"  {change_type}: {n_sub_match}/{len(subset)} ({100 * n_sub_match / len(subset):.1f}%)")

    for outcome in ("STAY", "OFFLOAD", "INFEASIBLE"):
        subset = [r for r in results if r["expected_outcome"] == outcome]
        if not subset:
            continue
        n_sub_match = sum(r["match"] for r in subset)
        print(f"  expected={outcome}: {n_sub_match}/{len(subset)} ({100 * n_sub_match / len(subset):.1f}%)")

    mismatches = [r["sample_id"] for r in results if not r["match"]]
    if mismatches:
        print(f"\nMismatches ({len(mismatches)}): {mismatches[:20]}{' ...' if len(mismatches) > 20 else ''}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit)
