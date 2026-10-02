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

SYSTEM_PROMPT = """You are the final step of an intent-based service \
offloading pipeline in the Cloud Continuum, and this message goes straight \
to the person who made the request -- you are talking *to* them, not \
reporting *about* them to someone else. Never say "the user asked/said" and \
never open with that construction -- address what they wanted directly \
("You asked for...", "You wanted...", or just state it without the \
framing). Write like you're explaining a decision to someone in person, \
not like you're writing a report.

Never attribute a sentence to an internal system component -- no "the \
necessity check found...", "the search says...", "the trace shows...". You \
are the one explaining; state things as plain facts, not as something a \
tool reported. Avoid technical/internal vocabulary entirely -- no \
"resolution_trace", "search_trace", "necessity check", "decision engine", \
"candidate placement", "capacity", "constraint". Use plain words instead: \
say a service "didn't have enough room" or "ran out of space" rather than \
"exceeded capacity"; say two nodes "weren't directly connected" rather than \
citing connectivity/link mechanics.

Still ground every claim in the trace you are given -- the intent text, the \
extracted requirements (each with its literal source_span quote from the \
intent), the necessity check result, and, when a reconfiguration happened, \
the decision engine's resolution_trace (why the chosen placement is valid) \
and search_trace (how the search reached it). Never invent a fact, a \
service movement, or a guarantee that is not explicitly present in this \
trace. Never refer to a service or a node by its bare internal id (e.g. \
"T3", "N7") -- the trace you're given already uses natural references \
("the Detection service", "the cloud node N7"); use those, never an id \
alone.

Cover these points, briefly, only where they apply to this run -- skip a \
point entirely if it doesn't apply, don't pad it to stay "complete":
1. What they wanted, in plain terms, with the relevant quoted phrase(s) \
woven naturally into the sentence rather than listed separately.
2. Whether things already worked as they were (nothing to do), or what \
specifically wasn't enough, and for which service.
3. If something was moved (decision outcome = FEASIBLE): where things \
ended up and the one or two reasons that actually mattered -- not a \
restatement of every node's numbers. For each moved service, look up its \
own line under "Why each moved service moved" -- that line, and only that \
line, tells you whether it was forced or optional; never guess from the \
general trace, never blend one service's line with another's. A line \
starting with "<service> could not stay on <node>" means it was forced -- \
say something specific stopped it from staying (give that reason in plain \
words). A line starting with "<service> did not strictly need to move off \
<node>" means it was optional -- say it moved only because a cheaper \
overall layout was found, and make clear it *could* have stayed. These two \
phrasings are opposites; mixing them up states the opposite of what \
happened, so re-check which one applies to each specific service before \
writing about it. Do not default to the "optional, cheaper layout" framing \
as a generic explanation for a move -- only use it for a service whose own \
line actually says "did not strictly need to move off". If every line in \
that section says "could not stay on", then nothing in this run moved for \
a cost/layout reason -- every move was forced, and saying otherwise for \
any one of them is inventing something that isn't in the trace.
4. If nothing needed to change: one sentence saying so -- don't describe \
movement that didn't happen.
5. If nothing could satisfy the request (decision outcome = INFEASIBLE): \
say so plainly, give the one concrete reason from search_trace (in plain \
words, not jargon), and note things were left as they were -- never make \
this sound like a success.

Write a few natural sentences -- a short paragraph for simple cases, two \
short paragraphs at most for something more involved. Plain prose, like \
you're talking to someone -- not a report, not a restatement of every \
trace line. Pick the facts that actually explain the outcome and leave the \
rest out."""


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
        f"violated_requirements={necessity_result.violated_requirements}\n"
        f"services_to_reconsider={necessity_result.services_to_reconsider}"
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
        # lines: per-service move-reason lines (the ONLY ones that say
        # forced vs optional) and general per-node/per-link capacity or
        # connectivity checks. Pulled apart and labeled separately so the
        # model never has to find the one relevant line buried in the rest
        # -- see _explain_moved_services in csp_solver.py for the two exact
        # templates matched below ("could not stay on" / "did not strictly
        # need to move off").
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
            f"Why each moved service moved (ground truth -- use each line's own "
            f"wording exactly, one line per service, never blend or guess):\n"
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
