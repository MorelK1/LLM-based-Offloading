"""LangGraph node: Intent Grounding (Requirements Extraction + Matching)."""

import json

from agent.model.schemas import Requirement
from agent.prompts.requirement_extraction import SYSTEM_PROMPT, build_user_prompt
from agent.states.state import AgentState
from agent.utils.config import load_config
from agent.utils.llm import get_llm


def intent_grounding_node(state: AgentState) -> dict:
    config = load_config()
    model = get_llm(config.llm)

    user_prompt = build_user_prompt(state["intent_text"], state["services"])
    response = model.invoke([("system", SYSTEM_PROMPT), ("human", user_prompt)])
    payload = json.loads(response.content)
    requirements = [Requirement(**item) for item in payload]

    # Matching: keep only requirements whose service exists in the app_context.
    # TODO: handle approximate matching (natural-language service name rather than exact ID).
    matched = [r for r in requirements if r.service in state["services"]]

    return {"requirements": matched}
