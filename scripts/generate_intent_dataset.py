"""Trial run: generate natural-language phrasing variants for the existing
ENACT-grounded Intent Grounding benchmark entries.

Ground truth (service/kpi_type/comparator/target_value/unit) is NOT
generated -- it's copied as-is from the hand-authored source entries, which
are themselves grounded in real ENACT measurements. The LLM only varies the
sentence. Output goes to a separate review file; the hand-written originals
are never modified.

Usage:
    source venv/bin/activate
    python scripts/generate_intent_dataset.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.prompts.intent_generation import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from agent.utils.llm_openrouter import get_openrouter_gpt_llm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/eval/intent_grounding_enact.jsonl"
SERVICES = ROOT / "data/eval/enact_services.json"
OUTPUT = ROOT / "data/eval/intent_grounding_enact_variants.jsonl"
VARIANTS_PER_ENTRY = 3


def main() -> None:
    with open(SERVICES) as f:
        services_raw = {
            s["service_id"]: s for s in json.load(f)["application_context"]["services"]
        }

    with open(SOURCE) as f:
        cases = [json.loads(line) for line in f]

    model = get_openrouter_gpt_llm()
    generated = []

    for case in cases:
        req = case["expected_requirements"][0]
        service = services_raw[req["service"]]
        for i in range(1, VARIANTS_PER_ENTRY + 1):
            user_prompt = build_user_prompt(
                service["name"],
                service["description"],
                req["kpi_type"],
                req["comparator"],
                req["target_value"],
                req["unit"],
            )
            response = model.invoke([("system", SYSTEM_PROMPT), ("human", user_prompt)])
            intent_text = response.content.strip()
            entry = {
                "id": f"{case['id']}-gen{i}",
                "source_id": case["id"],
                "intent_text": intent_text,
                "tags": case["tags"] + ["llm-generated"],
                "expected_requirements": case["expected_requirements"],
                "source": case["source"],
            }
            generated.append(entry)
            print(f"[{entry['id']}] {intent_text}")

    with open(OUTPUT, "w") as f:
        for entry in generated:
            f.write(json.dumps(entry) + "\n")

    print(f"\nWrote {len(generated)} generated variants to {OUTPUT}")


if __name__ == "__main__":
    main()
