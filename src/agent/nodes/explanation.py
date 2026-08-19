"""LangGraph node: Trace & Explanation Generation."""

from agent.prompts.explanation import SYSTEM_PROMPT
from agent.states.state import AgentState
from agent.utils.config import load_config
from agent.utils.llm import get_llm


def explanation_node(state: AgentState) -> dict:
    config = load_config()
    model = get_llm(config.llm)

    decision_result = state["decision_result"]
    user_prompt = (
        f"Necessity check: {state['necessity_result'].model_dump_json()}\n"
        f"Decision: {decision_result.model_dump_json() if decision_result else 'null'}\n"
        f"Requirements: {[r.model_dump() for r in state['requirements']]}"
    )
    response = model.invoke([("system", SYSTEM_PROMPT), ("human", user_prompt)])
    return {"explanation": response.content}
