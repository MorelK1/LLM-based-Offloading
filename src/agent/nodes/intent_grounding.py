"""LangGraph node: Intent Grounding (Requirements Extraction + Matching)."""

from agent.model.schemas import ExtractedRequirementList, Requirement
from agent.prompts.requirement_extraction import ZERO_SHOT_SYSTEM_PROMPT, build_user_prompt
from agent.states.state import AgentState
from agent.utils.llm_openrouter import get_openrouter_gpt_llm

# System prompt currently plugged into this node. Swap the imported constant
# above (ZERO_SHOT_SYSTEM_PROMPT / ONE_SHOT_SYSTEM_PROMPT / FEW_SHOT_SYSTEM_PROMPT)
# to test a different strategy. CoT variants are not implemented yet.
ACTIVE_SYSTEM_PROMPT = ZERO_SHOT_SYSTEM_PROMPT


def intent_grounding_node(state: AgentState) -> dict:
    # OpenRouter (openai/gpt-5.4-mini) is the default model here: NVIDIA API
    # Catalog's inference backend (utils/llm.py's get_openai_llm/get_mistral_llm)
    # proved too unreliable for iterating on prompt strategies -- see testbench.
    model = get_openrouter_gpt_llm().with_structured_output(ExtractedRequirementList)

    user_prompt = build_user_prompt(state["intent_text"], state["services"], state["flows"])
    result: ExtractedRequirementList = model.invoke(
        [("system", ACTIVE_SYSTEM_PROMPT), ("human", user_prompt)]
    )

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

    return {"requirements": matched}
