"""LangGraph node: Intent Grounding (Requirements Extraction + Matching)."""

import time

from agent.model.schemas import ExtractedRequirementList
from agent.prompts.requirement_extraction import (
    FEW_SHOT_SYSTEM_PROMPT,
    ONE_SHOT_SYSTEM_PROMPT,
    ZERO_SHOT_SYSTEM_PROMPT,
    build_user_prompt,
)
from agent.states.state import AgentState
from agent.utils.llm_openrouter import get_openrouter_gpt_llm
from agent.utils.requirement_validation import validate_and_normalize


PROMPT_STRATEGIES = {
    "zero_shot": ZERO_SHOT_SYSTEM_PROMPT,
    "one_shot": ONE_SHOT_SYSTEM_PROMPT,
    "few_shot": FEW_SHOT_SYSTEM_PROMPT,
}
DEFAULT_PROMPT_STRATEGY = "zero_shot"


def intent_grounding_node(
    state: AgentState,
    model: str | None = None,
    prompt_strategy: str = DEFAULT_PROMPT_STRATEGY,
) -> dict:
    """model overrides OPENROUTER_MODEL (.env) for this call when given --
    None keeps today's behavior exactly. prompt_strategy picks one of
    PROMPT_STRATEGIES (default "zero_shot", same prompt used before this was
    parameterized). Both exist so experimentation scripts can vary them
    without touching this file -- see graph.py:build_graph."""
    system_prompt = PROMPT_STRATEGIES[prompt_strategy]
    base_llm = get_openrouter_gpt_llm(model)
    resolved_model = base_llm.model_name  # the actual model used, even when `model` is None (.env fallback)
    # method="function_calling" is NOT a safe universal default here, unlike
    # for the baseline -- empirically model-dependent:
    # - deepseek/deepseek-v3.2: the default "json_schema" mode sometimes
    #   wraps its JSON in a markdown code fence ("```json\n[...]\n```"),
    #   which fails Pydantic's strict JSON parsing outright (no retry,
    #   sample lost) -- function_calling fixes this (validated: 3/3 OK on
    #   samples that previously failed).
    # - meta-llama/llama-4-scout: function_calling BREAKS IT COMPLETELY --
    #   every available endpoint (deepinfra, novita) lacks tool-calling
    #   support, so every call 404s ("No endpoints found").
    # - mistralai/mistral-small-3.2-24b-instruct: function_calling silently
    #   degrades extraction quality (returned empty requirements on samples
    #   deepseek correctly extracted from) -- not a crash, worse: wrong data.
    # So this is opt-in per model that's actually validated to need and
    # tolerate it, not a blanket switch.
    structured_output_method = "function_calling" if resolved_model.startswith("deepseek/") else "json_schema"
    llm = base_llm.with_structured_output(
        ExtractedRequirementList, include_raw=True, method=structured_output_method
    )

    user_prompt = build_user_prompt(state["intent_text"], state["services"], state["flows"])
    start = time.perf_counter()
    raw_result = llm.invoke([("system", system_prompt), ("human", user_prompt)])
    elapsed_s = time.perf_counter() - start

    parsing_error = raw_result["parsing_error"]
    result: ExtractedRequirementList = raw_result["parsed"] or ExtractedRequirementList(requirements=[])
    token_usage = raw_result["raw"].usage_metadata  # UsageMetadata dict, or None if the provider didn't report it

    # Validation + normalization + grounding, before anything downstream
    # sees a requirement -- comparator/target-type shape, target existence,
    # source_span literalness, value sanity, and unit conversion to each
    # KPI's canonical unit, all in one pass. requirement_id is assigned here
    # too, deterministically, to every survivor. See
    # utils/requirement_validation.py for the full "drop rather than guess"
    # policy and each rejection reason.
    # rejected isn't surfaced into AgentState yet -- available here for
    # diagnostics if that's wanted later, not wired through today.
    requirements, rejected = validate_and_normalize(
        result.requirements, state["intent_text"], state["services"], state["flows"]
    )

    return {
        "requirements": requirements,
        "extraction_model": resolved_model,
        "extraction_elapsed_s": elapsed_s,
        "extraction_token_usage": dict(token_usage) if token_usage else None,
        "extraction_parsing_error": str(parsing_error) if parsing_error else None,
    }
