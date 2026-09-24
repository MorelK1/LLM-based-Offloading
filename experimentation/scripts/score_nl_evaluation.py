"""Stage 2 of the NL evaluation pipeline: score experimentation/data/nl_evaluation_raw.jsonl
against ground truth. No LLM calls -- pure, deterministic, safe to re-run as often as the
scoring logic changes, without ever touching stage 1 again.

Scores extraction quality only (does intent_grounding_node's output match
expected_requirements) -- necessity_status/decision from stage 1 are carried
through unscored, for the notebook to analyze as a separate "decision layer".

Writes experimentation/data/nl_evaluation_scored.csv, one row per (case, run).

Run from the project root:
    venv/bin/python3 experimentation/scripts/score_nl_evaluation.py
"""

import csv
import json
from pathlib import Path

IN_PATH = Path("experimentation/data/nl_evaluation_raw.jsonl")
OUT_PATH = Path("experimentation/data/nl_evaluation_scored.csv")

VALUE_TOLERANCE = 0.05  # relative tolerance on target_value

FIELDS = [
    "service", "kpi_type", "comparator", "target_value", "unit",
]

CSV_COLUMNS = [
    "id", "dataset_source", "clarity_tier", "run",
    "expected_service", "expected_kpi_type",
    "n_expected", "n_extracted", "n_true_positive", "n_false_positive", "n_false_negative",
    "service_correct", "kpi_type_correct", "comparator_correct", "value_correct", "unit_correct",
    "exact_match", "error_category", "necessity_status", "decision_kind", "elapsed_s",
]


def values_close(a: float, b: float) -> bool:
    tol = max(abs(b) * VALUE_TOLERANCE, 1e-9)
    return abs(a - b) <= tol


def field_score(extracted: dict, expected: dict) -> int:
    score = 0
    score += extracted["service"] == expected["service"]
    score += extracted["kpi_type"] == expected["kpi_type"]
    score += extracted["comparator"] == expected["comparator"]
    score += extracted["unit"] == expected["unit"]
    score += values_close(extracted["target_value"], expected["target_value"])
    return score


def full_match(extracted: dict, expected: dict) -> bool:
    return field_score(extracted, expected) == 5


def match_lists(expected: list[dict], extracted: list[dict]) -> tuple[list[tuple[int, int | None]], list[int]]:
    """Greedy best-field-overlap matching. Returns (per-expected-item (idx, matched_extracted_idx
    or None), list of unmatched extracted indices (over-extraction / false positives))."""
    remaining = list(range(len(extracted)))
    matches = []
    for ei, exp in enumerate(expected):
        best_idx, best_score = None, -1
        for ai in remaining:
            s = field_score(extracted[ai], exp)
            if s > best_score:
                best_score, best_idx = s, ai
        # require at least service or kpi_type to line up before calling it "a match attempt"
        if best_idx is not None and best_score >= 2:
            matches.append((ei, best_idx))
            remaining.remove(best_idx)
        else:
            matches.append((ei, None))
    return matches, remaining


def decision_kind(decision) -> str:
    if decision == "NO_VALID_PLACEMENT":
        return "no_valid_placement"
    if isinstance(decision, dict) and len(decision) > 0:
        return "relocated"
    return "no_change"


def score_row(row: dict) -> dict:
    expected = row["expected_requirements"]
    extracted = row["extracted_requirements"]

    out = {
        "id": row["id"], "dataset_source": row["dataset_source"],
        "clarity_tier": row["clarity_tier"], "run": row["run"],
        "expected_service": expected[0]["service"] if expected else "",
        "expected_kpi_type": expected[0]["kpi_type"] if expected else "",
        "n_expected": len(expected), "n_extracted": len(extracted),
        "necessity_status": row["necessity_status"],
        "decision_kind": decision_kind(row["decision"]),
        "elapsed_s": row["elapsed_s"],
    }

    if len(expected) == 0:
        out.update({
            "n_true_positive": 0, "n_false_positive": len(extracted), "n_false_negative": 0,
            "service_correct": "", "kpi_type_correct": "", "comparator_correct": "",
            "value_correct": "", "unit_correct": "",
            "exact_match": len(extracted) == 0,
            "error_category": "ok" if len(extracted) == 0 else "hallucination_sur_vague",
        })
        return out

    matches, unmatched_extracted = match_lists(expected, extracted)

    tp = sum(1 for ei, ai in matches if ai is not None and full_match(extracted[ai], expected[ei]))
    fn = sum(1 for ei, ai in matches if ai is None or not full_match(extracted[ai], expected[ei]))
    fp = len(unmatched_extracted)

    # Field-level flags: only meaningful when len(expected) == 1 (today's dataset shape).
    # For len(expected) > 1, report the flags for the first expected item as a representative
    # sample -- a future multi-requirement-per-case extension should revisit this.
    ei0, ai0 = matches[0]
    if ai0 is not None:
        ext0, exp0 = extracted[ai0], expected[ei0]
        service_ok = ext0["service"] == exp0["service"]
        kpi_ok = ext0["kpi_type"] == exp0["kpi_type"]
        cmp_ok = ext0["comparator"] == exp0["comparator"]
        unit_ok = ext0["unit"] == exp0["unit"]
        val_ok = values_close(ext0["target_value"], exp0["target_value"])
    else:
        service_ok = kpi_ok = cmp_ok = unit_ok = val_ok = False

    exact_match = (fn == 0 and fp == 0)

    if ai0 is None:
        category = "sous_extraction"
    elif fp > 0:
        category = "sur_extraction"
    elif not service_ok:
        category = "confusion_service"
    elif not kpi_ok:
        category = "confusion_kpi"
    elif not cmp_ok:
        category = "comparateur_inverse"
    elif not unit_ok:
        category = "unite_incorrecte"
    elif not val_ok:
        category = "valeur_incorrecte"
    else:
        category = "ok"

    out.update({
        "n_true_positive": tp, "n_false_positive": fp, "n_false_negative": fn,
        "service_correct": service_ok, "kpi_type_correct": kpi_ok,
        "comparator_correct": cmp_ok, "value_correct": val_ok, "unit_correct": unit_ok,
        "exact_match": exact_match, "error_category": category,
    })
    return out


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
    n_exact = sum(1 for r in scored_rows if r["exact_match"])
    print(f"Scored {n} rows -> {OUT_PATH}")
    print(f"Overall exact-match rate: {n_exact}/{n} ({100 * n_exact / n:.0f}%)")


if __name__ == "__main__":
    main()
