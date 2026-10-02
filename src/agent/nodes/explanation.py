"""LangGraph node: Trace & Explanation Generation."""

import time

from agent.prompts.explanation import SYSTEM_PROMPT, build_user_prompt
from agent.states.state import AgentState
from agent.utils.llm_openrouter import get_openrouter_gpt_llm


def explanation_node(state: AgentState, model: str | None = None) -> dict:
    # OpenRouter (openai/gpt-5.4-mini by default), same choice as
    # intent_grounding_node: NVIDIA API Catalog's inference backend
    # (get_mistral_llm) proved too unreliable in practice -- see testbench /
    # README. model overrides OPENROUTER_MODEL (.env) when given.
    llm = get_openrouter_gpt_llm(model)

    user_prompt = build_user_prompt(
        state["intent_text"],
        state["requirements"],
        state["necessity_result"],
        state["decision_result"],
        state["services"],
        state["nodes"],
        state["flows"],
    )
    start = time.perf_counter()
    response = llm.invoke([("system", SYSTEM_PROMPT), ("human", user_prompt)])
    elapsed_s = time.perf_counter() - start

    # No structured output here, so the raw AIMessage is already what
    # .invoke() returns -- unlike intent_grounding_node, no include_raw needed.
    token_usage = response.usage_metadata
    return {
        "explanation": response.content,
        "explanation_model": llm.model_name,  # actual model used, even when `model` is None (.env fallback)
        "explanation_elapsed_s": elapsed_s,
        "explanation_token_usage": dict(token_usage) if token_usage else None,
    }
