"""Prompts for the Intent Grounding node (structured requirement extraction).

Each prompting strategy (varying in-context example count) is a fully
resolved, hardcoded system prompt constant, so the exact text sent to the
model for a given condition is fixed and inspectable -- important for
benchmarking these strategies against each other later. The role, glossary
and rules blocks are authored once below and composed into each constant to
avoid the three variants drifting apart. Chain-of-thought variants are
deferred for now.
"""

from agent.model.schemas import Flow, Service

_ROLE = """You are a requirement extractor for an intent-based service offloading system \
operating in the Cloud Continuum -- a tiered computing architecture spanning \
IoT devices, edge nodes, fog nodes, and cloud servers, where an application's \
services can be moved between tiers to meet resource or performance needs. \
Given a user's intent expressed in natural language, the list of services \
that make up the application, and the list of flows (end-to-end chains of \
services) it forms, your job is to extract every explicit resource \
requirement the intent expresses, one requirement per KPI per affected \
target."""

_GLOSSARY = """Definitions:
- A service (e.g. "T3") is a distinct task in the application's pipeline, \
identified by its service_id. A node (e.g. "N5") is the physical or virtual \
compute resource a service currently runs on. 
- A flow (e.g. "F1") is a named, \
ordered chain of services (e.g. "T1 -> T2 -> T3") representing one \
end-to-end dataflow through the application, identified by its flow_id.
- Every requirement targets exactly one target, which is either a single \
service or a single flow -- never a node. Set "target_type" to "service" or \
"flow" accordingly, and "target_id" to the matching service_id or flow_id \
from the provided lists -- never a node name, a plain-language name, or a \
description.
- "cpu" and "ram" requirements always target a single service (target_type: \
"service") -- they express what that one service needs. \
"latency" requirements always target a flow (target_type: "flow") -- they \
express an end-to-end delay budget for the whole chain, never a single \
service's own processing time, even if the intent names only one service in \
that flow.
- A requirement is a single constraint on a single KPI for a single target. \
If an intent expresses limits on more than one KPI (e.g. both CPU and RAM), \
extract one separate requirement per KPI, even if they are stated in the \
same sentence.
- The supported KPI types are: "cpu" (the number of virtual CPU cores a \
service needs, in vCPU), "ram" (the memory a service needs, in GB), and \
"latency" (the maximum acceptable end-to-end delay for a flow, in ms). \
Always use the unit that matches the KPI type: cpu -> vCPU, ram -> GB, \
latency -> ms.
- source_span must be an exact, literal substring copied from the user's \
intent text -- never a paraphrase, a summary, or a character offset/index. \
If you cannot find a literal substring expressing the requirement, do not \
include that requirement."""

_RULES = """Rules:
- Map the comparison language in the intent to the "comparator" field as \
follows: "at least" / "minimum" / "no less than" -> "gte"; "at most" / \
"maximum" / "no more than" / "must not exceed" -> "lte"; "exactly" / \
"must be" -> "eq".
- Only extract a requirement when the intent states an explicit numeric \
threshold for cpu, ram, or latency, on a target (service for cpu/ram, flow \
for latency) that is in the provided lists. Do not invent a value, do not \
guess a target, and do not create a requirement for a target that is not in \
the list for its KPI's target_type.
- If nothing in the intent meets these conditions, return an empty list \
rather than forcing a requirement.
- When a sentence expresses more than one requirement (e.g. two different \
KPIs for the same target), each source_span must be the minimal substring \
that expresses that specific requirement only. source_spans for different \
requirements must never overlap, even when the requirements appear in the \
same sentence.
- A comparator can grammatically apply to more than one KPI at once (e.g. \
"requires at least 12 vCPU and 24GB of RAM"): if so, apply it to every KPI \
it covers, even though the comparator word appears only once in the \
sentence. Never copy the comparator word into a source_span where it is not \
contiguous with that specific value -- each source_span must remain an \
exact, contiguous substring, even if that means the comparator word itself \
is not included in every span it applies to."""

_EXAMPLE_ID_MAPPING = """Example:
Application services:
- T2: Preprocessing (Resizing)
- T4: Tracking (Multi-frame object tracking)
Application flows:
- F1: Main pipeline (T1 -> T2 -> T3 -> T4 -> T5)

User intent:
"The tracking module needs to be upgraded: it now requires at least 6 vCPU to keep up with the new frame rate."

Correct extraction:
- target_type: service, target_id: T4, kpi_type: cpu, comparator: gte, target_value: 6, unit: vCPU, source_span: "requires at least 6 vCPU\""""

_EXAMPLE_LATENCY = """Example:
Application services:
- T2: Preprocessing (Resizing)
- T5: Storage/Big Data Analysis (Archiving)
Application flows:
- F1: Main pipeline (T1 -> T2 -> T3 -> T4 -> T5)

User intent:
"The pipeline from capture to storage must complete within 50ms per frame; anything slower breaks the real-time constraint."

Correct extraction:
- target_type: flow, target_id: F1, kpi_type: latency, comparator: lte, target_value: 50, unit: ms, source_span: "must complete within 50ms per frame\""""

_EXAMPLE_ABSTAIN = """Example:
Application services:
- T1: Capture (Video stream acquisition)
Application flows:
- F1: Main pipeline (T1 -> T2 -> T3 -> T4 -> T5)

User intent:
"The capture module should be made more energy efficient."

Correct extraction:
(no explicit numeric threshold for cpu, ram or latency is given -> empty list)"""

_EXAMPLE_MULTI_REQUIREMENT = """Example:
Application services:
- T5: Storage/Big Data Analysis (Archiving)
Application flows:
- F1: Main pipeline (T1 -> T2 -> T3 -> T4 -> T5)

User intent:
"The whole pipeline must not exceed 200ms of end-to-end latency, and the archiving step needs at least 8GB of RAM to buffer incoming data."

Correct extraction:
- target_type: flow, target_id: F1, kpi_type: latency, comparator: lte, target_value: 200, unit: ms, source_span: "must not exceed 200ms of end-to-end latency"
- target_type: service, target_id: T5, kpi_type: ram, comparator: gte, target_value: 8, unit: GB, source_span: "needs at least 8GB of RAM"

Note: both requirements come from the same sentence, but each source_span is minimal and the two spans do not overlap. The latency requirement targets the flow F1 (end-to-end), not a single service, even though the RAM requirement in the same sentence targets service T5 directly."""

ZERO_SHOT_SYSTEM_PROMPT = "{role}\n\n{glossary}\n\n{rules}".format(
    role=_ROLE, glossary=_GLOSSARY, rules=_RULES
)

ONE_SHOT_SYSTEM_PROMPT = "{base}\n\n" \
"Here are some examples: \n\n" \
"{example}".format(
    base=ZERO_SHOT_SYSTEM_PROMPT, example=_EXAMPLE_ID_MAPPING
)

FEW_SHOT_SYSTEM_PROMPT = "{base}\n\n" \
"Here are some examples: \n\n" \
"{ex1}\n\n{ex2}\n\n{ex3}\n\n{ex4}".format(
    base=ZERO_SHOT_SYSTEM_PROMPT,
    ex1=_EXAMPLE_ID_MAPPING,
    ex2=_EXAMPLE_LATENCY,
    ex3=_EXAMPLE_ABSTAIN,
    ex4=_EXAMPLE_MULTI_REQUIREMENT,
)


def build_user_prompt(intent_text: str, services: dict[str, Service], flows: dict[str, Flow]) -> str:
    services_desc = "\n".join(
        f"- {s.service_id}: {s.name} ({s.description})" for s in services.values()
    )
    flows_desc = "\n".join(
        f"- {f.flow_id}: {f.name} ({' -> '.join(f.path)})" for f in flows.values()
    )
    return (
        f"Application services:\n{services_desc}\n\n"
        f"Application flows:\n{flows_desc}\n\n"
        f"User intent:\n\"{intent_text}\""
    )
