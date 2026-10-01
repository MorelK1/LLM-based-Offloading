"""LangGraph node: Intent Grounding (Requirements Extraction + Matching)."""

import time

from agent.model.schemas import ExtractedRequirementList, Requirement
from agent.prompts.requirement_extraction import (
    FEW_SHOT_SYSTEM_PROMPT,
    ONE_SHOT_SYSTEM_PROMPT,
    ZERO_SHOT_SYSTEM_PROMPT,
    build_user_prompt,
)
from agent.states.state import AgentState
from agent.utils.llm_openrouter import get_openrouter_gpt_llm

# Default prompting strategy when intent_grounding_node is called without an
# explicit prompt_strategy -- i.e. the production graph's current behavior,
# unchanged. CoT variants are not implemented yet.
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
    # OpenRouter (openai/gpt-5.4-mini by default) is used here: NVIDIA API
    # Catalog's inference backend (utils/llm.py's get_openai_llm/get_mistral_llm)
    # proved too unreliable for iterating on prompt strategies -- see testbench.
    # include_raw=True: keeps the raw AIMessage (for usage_metadata -- token
    # counts) instead of discarding it once structured parsing succeeds; it
    # also means a parsing failure is now a value ("parsed": None) rather
    # than an exception, handled below.
    llm = get_openrouter_gpt_llm(model).with_structured_output(
        ExtractedRequirementList, include_raw=True
    )

    user_prompt = build_user_prompt(state["intent_text"], state["services"], state["flows"])
    start = time.perf_counter()
    raw_result = llm.invoke([("system", system_prompt), ("human", user_prompt)])
    elapsed_s = time.perf_counter() - start

    parsing_error = raw_result["parsing_error"]
    result: ExtractedRequirementList = raw_result["parsed"] or ExtractedRequirementList(requirements=[])
    token_usage = raw_result["raw"].usage_metadata  # UsageMetadata dict, or None if the provider didn't report it

    # requirement_id is assigned here, deterministically, rather than left to the LLM.
    requirements = [
        Requirement(requirement_id=f"req-{i:03d}", **extracted.model_dump())
        for i, extracted in enumerate(result.requirements, start=1)
    ]

    # Matching: keep only requirements whose target actually exists in the
    # app_context -- a service for target_type="service", a flow for "flow".
    # TODO: handle approximate matching (natural-language name rather than exact ID).
    matched = [
        r for r in requirements
        if (r.target_type == "service" and r.target_id in state["services"])
        or (r.target_type == "flow" and r.target_id in state["flows"])
    ]

    return {
        "requirements": matched,
        "extraction_elapsed_s": elapsed_s,
        "extraction_token_usage": dict(token_usage) if token_usage else None,
        "extraction_parsing_error": str(parsing_error) if parsing_error else None,
    }
