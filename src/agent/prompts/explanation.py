"""Prompt for the Trace & Explanation Generation node.

Unlike a short user-facing blurb, this node produces a full audit-style
synthesis of the whole pipeline run -- grounded explicitly in every trace
collected along the way (the intent text, each requirement's source_span,
the necessity check outcome, and the decision engine's resolution_trace /
search_trace when a reconfiguration happened).
"""

from agent.model.schemas import DecisionResult, NecessityCheckResult, Requirement

SYSTEM_PROMPT = """You are the final step of an intent-based service \
offloading pipeline in the Cloud Continuum. Your job is not to write a \
short blurb -- it is to produce a complete, faithful synthesis of \
everything the pipeline did, from the user's original intent down to the \
final outcome, so a reader can audit the whole decision without looking at \
raw logs.

Ground every claim in the trace you are given -- the intent text, the \
extracted requirements (each with its literal source_span quote from the \
intent), the necessity check result, and, when a reconfiguration happened, \
the decision engine's resolution_trace (why the chosen placement is valid) \
and search_trace (how the search reached it). Never invent a fact, a \
service movement, or a guarantee that is not explicitly present in this \
trace.

Structure your synthesis in this order:
1. The user's original intent, in your own words, citing the relevant \
source_span quote(s) for the requirement(s) you extracted from it.
2. The necessity check outcome: which requirements (if any) were violated \
against the current placement, and which service(s) that implicates.
3. If a decision was made (status = reconfiguration_required): the new \
placement, grounded in the resolution_trace entries that justify it -- \
restate them in plain language rather than copying them verbatim. For \
every moved service, resolution_trace contains one explicit entry of the \
form "<service> could not stay on <node>: <reason>" (a genuine constraint \
forced the move -- cite the reason) or "<service> did not strictly need to \
move off <node> ... found a cheaper overall configuration" (the move was \
optional, purely for infrastructure cost, not a violated requirement of \
that service). Use exactly this distinction for every moved service -- \
never claim a service "had to" move unless its entry says so, and never \
invent a mechanism (e.g. "for connectivity") that isn't the one stated in \
that service's entry.
4. If no decision was made (status = no_action_needed): say plainly that \
the current placement already satisfies every requirement -- do not \
describe any movement, since none happened.

Write in English, in clear prose (not bullet points), long enough to cover \
all four points above -- do not artificially compress this into a couple \
of sentences."""


def build_user_prompt(
    intent_text: str,
    requirements: list[Requirement],
    necessity_result: NecessityCheckResult,
    decision_result: DecisionResult | None,
) -> str:
    requirements_desc = "\n".join(
        f"- {r.requirement_id}: {r.service} {r.kpi_type} {r.comparator} "
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
    else:
        resolution = "\n".join(
            f"  - {line}" for line in decision_result.resolution_trace
        ) or "  (none)"
        search = "\n".join(
            f"  - {line}" for line in decision_result.search_trace
        ) or "  (none)"
        decision_desc = (
            f"placement_changes={decision_result.decision}\n"
            f"new_configuration={decision_result.new_configuration}\n"
            f"resolution_trace (why the chosen placement is valid):\n{resolution}\n"
            f"search_trace (how the search reached it):\n{search}"
        )

    return (
        f"User intent:\n\"{intent_text}\"\n\n"
        f"Extracted requirements:\n{requirements_desc}\n\n"
        f"Necessity check:\n{necessity_desc}\n\n"
        f"Decision:\n{decision_desc}"
    )
