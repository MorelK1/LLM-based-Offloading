"""Prompt for generating natural-language intents from a known ground-truth
requirement tuple -- used to build/expand the Intent Grounding benchmark
dataset. Not part of the runtime pipeline.

This is the reverse direction of requirement_extraction.py: here the
structured requirement is already known (grounded in real data), and the
model must phrase a plausible sentence for it. Explicit anti-canonical-
phrasing rules are included because a generator left unguided naturally
drifts toward clean, textbook wording ("at least X"), which would make the
benchmark artificially easy for LLM-based extraction to score well on.
"""

SYSTEM_PROMPT = """You write short, natural intent sentences for a Cloud \
Continuum service offloading system, as if written by a real operator or \
developer -- not a textbook example.

You will be given a structured requirement (a service, a KPI, a comparator, \
a target value and unit). Write exactly ONE sentence in English that a real \
person would plausibly write to express that same requirement, and nothing \
else.

Rules:
- The sentence must express the exact same requirement -- same service, \
same KPI, same comparator direction, same numeric value and unit. Never \
change the meaning, never soften or exaggerate the threshold.
- Avoid canonical, textbook phrasing. Do NOT default to "at least X" for a \
minimum or "no more than X" for a maximum every time -- vary the \
construction (e.g. "won't fit in less than X", "can't go over X", "needs X \
or more", "should stay below X", "X is the ceiling here").
- Vary sentence structure and length across different requirements -- do \
not always start with the service name, do not always use the same \
grammatical pattern.
- Sound like a real, slightly informal operator note or ticket comment, not \
a polished specification sentence.
- Do not add extra numbers, KPIs, or services beyond the one given.
- Output only the sentence, no quotes, no explanation, no markdown."""


def build_user_prompt(
    service_name: str,
    service_description: str,
    kpi_type: str,
    comparator: str,
    target_value: float,
    unit: str,
) -> str:
    comparator_meaning = {
        "gte": "at least (a minimum)",
        "lte": "at most (a maximum)",
        "eq": "exactly",
    }[comparator]
    return (
        f"Service: {service_name} ({service_description})\n"
        f"Requirement: {kpi_type}, {comparator_meaning}, {target_value}{unit}"
    )
