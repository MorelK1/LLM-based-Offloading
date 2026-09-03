"""LangGraph node: Intent Grounding (Requirements Extraction + Matching)."""

from agent.model.schemas import ExtractedRequirementList, Requirement
from agent.prompts.requirement_extraction import ZERO_SHOT_SYSTEM_PROMPT, build_user_prompt
from agent.states.state import AgentState
from agent.utils.llm import get_openai_llm

# System prompt currently plugged into this node. Swap the imported constant
# above (ZERO_SHOT_SYSTEM_PROMPT / ONE_SHOT_SYSTEM_PROMPT / FEW_SHOT_SYSTEM_PROMPT)
# to test a different strategy. CoT variants are not implemented yet.
ACTIVE_SYSTEM_PROMPT = ZERO_SHOT_SYSTEM_PROMPT


def intent_grounding_node(state: AgentState) -> dict:
    model = get_openai_llm().with_structured_output(ExtractedRequirementList)

    user_prompt = build_user_prompt(state["intent_text"], state["services"])
    result: ExtractedRequirementList = model.invoke(
        [("system", ACTIVE_SYSTEM_PROMPT), ("human", user_prompt)]
    )

    # requirement_id is assigned here, deterministically, rather than left to the LLM.
    requirements = [
        Requirement(requirement_id=f"req-{i:03d}", **extracted.model_dump())
        for i, extracted in enumerate(result.requirements, start=1)
    ]

    # Matching: keep only requirements whose service exists in the app_context.
    # TODO: handle approximate matching (natural-language service name rather than exact ID).
    matched = [r for r in requirements if r.service in state["services"]]

    return {"requirements": matched}
