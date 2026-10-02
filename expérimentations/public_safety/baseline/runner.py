"""Calls the single-LLM baseline directly -- no LangGraph here, there's only
one call to make, unlike the real pipeline's four-node graph."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for prompt.py/schema.py

from agent.model.schemas import Flow, Link, Node, Service  # noqa: E402
from agent.utils.llm_openrouter import get_openrouter_gpt_llm  # noqa: E402
from prompt import DEFAULT_PROMPT_STRATEGY, PROMPT_STRATEGIES, build_user_prompt  # noqa: E402
from schema import BaselineResult  # noqa: E402


def run_baseline(
    intent_text: str,
    services: dict[str, Service],
    flows: dict[str, Flow],
    nodes: dict[str, Node],
    links: list[Link],
    model: str | None = None,
    prompt_strategy: str = DEFAULT_PROMPT_STRATEGY,
) -> dict:
    """Returns {"result": BaselineResult | None, "model": str, "elapsed_s":
    float, "token_usage": dict | None, "parsing_error": str | None} -- same
    shape convention as intent_grounding_node's telemetry, so scoring code
    can treat both the same way. "model" is the actual resolved model name,
    even when `model` (the param) is None (.env's OPENROUTER_MODEL
    fallback) -- without this, a record from a None-override run can't say
    which model actually ran it."""
    system_prompt = PROMPT_STRATEGIES[prompt_strategy]
    base_llm = get_openrouter_gpt_llm(model)
    resolved_model = base_llm.model_name
    # method="function_calling": the default "json_schema" mode (OpenAI
    # strict structured outputs) rejects BaselineResult outright --
    # new_placement is an open-ended dict[str, str], and strict mode requires
    # every object schema to fully enumerate its properties, which an
    # arbitrary service_id -> node_id mapping can't do. function_calling
    # doesn't enforce that, at the cost of weaker guarantees (pydantic still
    # validates the result after parsing, same as always).
    llm = base_llm.with_structured_output(BaselineResult, include_raw=True, method="function_calling")
    user_prompt = build_user_prompt(intent_text, services, flows, nodes, links)

    start = time.perf_counter()
    raw = llm.invoke([("system", system_prompt), ("human", user_prompt)])
    elapsed_s = time.perf_counter() - start

    token_usage = raw["raw"].usage_metadata
    return {
        "result": raw["parsed"],
        "model": resolved_model,
        "elapsed_s": elapsed_s,
        "token_usage": dict(token_usage) if token_usage else None,
        "parsing_error": str(raw["parsing_error"]) if raw["parsing_error"] else None,
    }
