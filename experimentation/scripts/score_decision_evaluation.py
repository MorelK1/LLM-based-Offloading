"""Scores experimentation/data/decision_evaluation_raw.jsonl: does
necessity_checker's observed status match the case's expected_necessity_status?
No LLM involved, purely deterministic -- safe to re-run any time.

Error taxonomy (derived directly from necessity_checker.py's actual logic, not
guessed): a mismatch is either
  - "kpi_non_gere": the requirement's kpi_type isn't "cpu"/"ram"/"latency" --
    necessity_checker.py's _KPI_TO_NODE_FIELD lookup returns None and the
    requirement is silently skipped (continue), so it can never surface as a
    violation regardless of the real value.
  - "capacite_brute_vs_cible": kpi_type is "cpu" or "ram" -- the requirement is
    compared directly to the node's raw total capacity field (an int, native
    unit), not to any per-service usage or unit-converted figure.
  - "correct": expected == observed.

Writes experimentation/data/decision_evaluation_scored.csv, one row per case.

Run from the project root:
    venv/bin/python3 experimentation/scripts/score_decision_evaluation.py
"""

import csv
import json
from pathlib import Path

IN_PATH = Path("experimentation/data/decision_evaluation_raw.jsonl")
OUT_PATH = Path("experimentation/data/decision_evaluation_scored.csv")

UNHANDLED_KPIS = {"energy", "bandwidth", "storage", "network_in", "network_out"}

CSV_COLUMNS = [
    "id", "dataset_source", "kpi_type", "service",
    "expected_necessity_status", "necessity_status", "status_correct",
    "error_category", "is_offload_trigger", "decision_kind",
]


def decision_kind(decision) -> str:
    if decision == "NO_VALID_PLACEMENT":
        return "no_valid_placement"
    if isinstance(decision, dict) and len(decision) > 0:
        return "relocated"
    return "no_change"


def score_row(row: dict) -> dict:
    req = row["expected_requirements"][0]
    status_correct = row["necessity_status"] == row["expected_necessity_status"]

    if status_correct:
        category = "correct"
    elif req["kpi_type"] in UNHANDLED_KPIS:
        category = "kpi_non_gere"
    elif req["kpi_type"] in ("cpu", "ram"):
        category = "capacite_brute_vs_cible"
    else:
        category = "autre"

    return {
        "id": row["id"], "dataset_source": row["dataset_source"],
        "kpi_type": req["kpi_type"], "service": req["service"],
        "expected_necessity_status": row["expected_necessity_status"],
        "necessity_status": row["necessity_status"],
        "status_correct": status_correct,
        "error_category": category,
        "is_offload_trigger": "offload-trigger" in row.get("tags", []),
        "decision_kind": decision_kind(row["decision"]),
    }


def main() -> None:
    with open(IN_PATH) as f:
        raw_rows = [json.loads(line) for line in f]

    scored_rows = [score_row(r) for r in raw_rows]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(scored_rows)

    n = len(scored_rows)
    n_correct = sum(1 for r in scored_rows if r["status_correct"])
    print(f"Scored {n} rows -> {OUT_PATH}")
    print(f"necessity_status correct: {n_correct}/{n} ({100 * n_correct / n:.0f}%)")


if __name__ == "__main__":
    main()
