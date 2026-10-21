"""Prompt for the Trace & Explanation Generation node.

Produces a natural, readable synthesis of the pipeline run -- grounded in
the actual trace (intent, extracted requirements, necessity check,
decision engine's resolution_trace/search_trace when relevant), but written
the way a person would actually explain a decision to a colleague, not as a
line-by-line restatement of every trace entry.

Services and nodes are never referred to by their bare internal id in the
final text: service_id (e.g. "T3") is replaced by the service's own name
(e.g. "the Detection service"), node_id (e.g. "N7") is qualified with its
tier (e.g. "the cloud node N7") -- the end user knows service names, not
internal ids, and a tier gives a node meaning without requiring one.
_translate_ids performs this substitution directly on the trace text fed to
the model, rather than leaving it to infer the mapping itself.
"""

import re

from agent.model.schemas import DecisionResult, Flow, NecessityCheckResult, Node, Requirement, Service


_ROLE = """You are an explanation assistant for an intent-driven
service reconfiguration system operating across the
Cloud-Edge-IoT Continuum.

You communicate directly with the operator who
submitted the request.
"""

_TASK = """Explain the outcome of the operator's request
in clear and concise natural language.

Using the operator's intent, the extracted requirements,
the necessity assessment, and the decision result,
explain whether the current configuration can satisfy
the updated requirements and, when applicable, what
reconfiguration is proposed and why.
"""

_GLOSSARY = """Definitions:
- Service: an application component hosted on a
  computing node.
- Flow: an end-to-end sequence of application services.
- Current placement: the configuration before the request.
- Proposed placement: the configuration calculated to
  satisfy the updated requirements.
- Relocation: moving a service from its current node
  to another node.

Necessity check:
- Determines whether the current placement already
  satisfies the updated requirements. If it does, no
  reconfiguration is attempted and there is no decision
  result at all.

Decision outcomes (only exist when reconfiguration was
attempted):
- FEASIBLE: a new placement satisfying the modeled
  requirements has been found.
- INFEASIBLE: no placement can satisfy all modeled
  requirements.
"""

_RULES = """Follow these instructions :

1. FACTUAL ACCURACY
- Use only information provided in the execution context.
- Never invent resource shortages, latency violations,
  service movements, or reasons for a decision.
- Do not infer individual relocation causes from
  general violations or solver status.
- If a reason is not available, explain the outcome
  without inventing one.
- Do not claim that services have been physically moved
  unless execution is explicitly confirmed.

2. EXPLANATION CONTENT
- Briefly explain the requested change.
- State whether the current configuration satisfies
  the updated requirements.
- If reconfiguration is proposed, identify the moved
  services and their destinations.
- Explain the main reasons for reconfiguration when
  they are supported by the provided information.
- Avoid listing every numerical value or repeating
  the complete execution trace.

3. OUTCOME-SPECIFIC RULES
- NO RECONFIGURATION NEEDED (necessity check only, no
  decision result exists):
  Explain that the existing configuration already
  satisfies the updated requirements.
  Do not describe any relocation.

- FEASIBLE:
  Describe the proposed placement changes.
  Explain that the new configuration satisfies the
  modeled requirements.
  Only claim minimum relocations when optimality
  has been established by the solver.

- INFEASIBLE:
  Explain that no configuration satisfies all the
  updated requirements under the modeled constraints.
  Give a concrete reason only if it is explicitly
  supported by the supplied information.
  Make clear that no new configuration was applied.

4. LANGUAGE AND STYLE
- Address the operator directly.
- Never refer to the operator as "the user".
- Do not mention internal components, algorithms,
  raw trace fields, or solver terminology.
- Refer to services and nodes by descriptive names
  when available, rather than bare identifiers.
- Use clear, natural language suitable for an
  operator without optimization expertise.
- Avoid unnecessary technical explanations.

5. OUTPUT
- Write a short paragraph for simple cases.
- Use at most two short paragraphs for complex cases.
- Focus on the decision and the most relevant reasons.
- Return only the explanation text.
"""

SYSTEM_PROMPT = "\n\n".join([
    _ROLE.strip(),
    _TASK.strip(),
    _GLOSSARY.strip(),
    _RULES.strip(),
])



def _translate_ids(
    text: str, services: dict[str, Service], nodes: dict[str, Node], flows: dict[str, Flow]
) -> str:
    """Replaces every whole-word service_id/node_id/flow_id in text with a
    natural reference -- "the <Name> service", "the <tier> node <id>", "the
    <Name> flow" -- so the model never has to guess the mapping itself, and
    never has a reason to fall back to a bare id in its own prose.

    Some datasets (public_safety) use bare-digit node ids ("0", "1", "2").
    \\b alone isn't enough there -- "\\b0\\b" also matches the "0" in a
    decimal number like "32.0" or "0.5" (a period is a non-word character,
    so a word boundary exists on either side of that digit too), corrupting
    numbers in the resolution_trace text ("32.0" -> "32.the edge node 0").
    The lookaround guards below exclude a match immediately preceded by
    "<digit>." or followed by ".<digit>" -- i.e. the id looks like it's
    actually a decimal's integer or fractional part, not a standalone id."""
    def _sub(pattern_id: str, replacement: str, text: str) -> str:
        pattern = rf"(?<!\d\.)\b{re.escape(pattern_id)}\b(?!\.\d)"
        return re.sub(pattern, replacement, text)

    for sid, service in sorted(services.items(), key=lambda kv: -len(kv[0])):
        # Some datasets (public_safety) name services "X Service" already --
        # appending " service" unconditionally would read "the X Service
        # service". Only append it when the name doesn't already end with it.
        label = service.name if service.name.strip().lower().endswith("service") else f"{service.name} service"
        text = _sub(sid, f"the {label}", text)
    for nid, node in sorted(nodes.items(), key=lambda kv: -len(kv[0])):
        text = _sub(nid, f"the {node.tier} node {nid}", text)
    for fid, flow in sorted(flows.items(), key=lambda kv: -len(kv[0])):
        text = _sub(fid, f"the {flow.name} flow", text)
    return text


def build_user_prompt(
    intent_text: str,
    requirements: list[Requirement],
    necessity_result: NecessityCheckResult,
    decision_result: DecisionResult | None,
    services: dict[str, Service],
    nodes: dict[str, Node],
    flows: dict[str, Flow],
) -> str:
    requirements_desc = "\n".join(
        f"- {r.requirement_id}: {r.target_type}:{r.target_id} {r.kpi_type} {r.comparator} "
        f"{r.target_value}{r.unit} (source: \"{r.source_span}\")"
        for r in requirements
    ) or "(none extracted)"

    necessity_desc = (
        f"status={necessity_result.status}\n"
        f"violated_constraints={necessity_result.violated_constraints}"
    )

    if decision_result is None:
        decision_desc = "No reconfiguration was performed (necessity check found none needed)."
    elif decision_result.outcome == "INFEASIBLE":
        search = "\n".join(
            f"  - {line}" for line in decision_result.search_trace
        ) or "  (none)"
        decision_desc = (
            "outcome=INFEASIBLE: no candidate placement satisfies every "
            "requirement simultaneously -- the configuration was left "
            f"unchanged (current_configuration={decision_result.new_configuration}).\n"
            f"search_trace (why no placement was found):\n{search}"
        )
    else:
        # resolution_trace is a flat list mixing two different kinds of
        # lines: per-service move-reason lines and general per-node/
        # per-flow capacity or latency checks. Pulled apart and labeled
        # separately so the model doesn't have to find the one relevant
        # line buried in the rest -- see pipeline.py:explain_moved_services
        # (shared by both the brute-force and CP-SAT backends) for the two
        # exact templates matched below.
        move_reasons = [
            line
            for line in decision_result.resolution_trace
            if " could not stay on " in line or " did not strictly need to move off " in line
        ]
        other_checks = [
            line
            for line in decision_result.resolution_trace
            if line not in move_reasons
        ]
        move_reasons_desc = "\n".join(f"  - {line}" for line in move_reasons) or "  (none)"
        other_checks_desc = "\n".join(f"  - {line}" for line in other_checks) or "  (none)"
        search = "\n".join(
            f"  - {line}" for line in decision_result.search_trace
        ) or "  (none)"
        decision_desc = (
            f"outcome=FEASIBLE\n"
            f"placement_changes={decision_result.decision}\n"
            f"new_configuration={decision_result.new_configuration}\n"
            f"Why each moved service moved (ground truth -- each service's own "
            f"line is its one and only reason; never attribute one service's "
            f"line to another):\n"
            f"{move_reasons_desc}\n"
            f"Other checks confirming the new placement is valid:\n{other_checks_desc}\n"
            f"search_trace (how the search reached it):\n{search}"
        )

    prompt = (
        f"User intent:\n\"{intent_text}\"\n\n"
        f"Extracted requirements:\n{requirements_desc}\n\n"
        f"Necessity check:\n{necessity_desc}\n\n"
        f"Decision:\n{decision_desc}"
    )
    # Translated last, over the whole assembled prompt, so every id --
    # wherever it came from (requirements, necessity, raw trace lines) --
    # gets the same natural substitution in one pass.
    return _translate_ids(prompt, services, nodes, flows)
