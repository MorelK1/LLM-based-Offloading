"""LangGraph node: Trace & Explanation Generation."""

from agent.prompts.explanation import SYSTEM_PROMPT
from agent.states.state import AgentState
from agent.utils.llm import get_mistral_llm


def explanation_node(state: AgentState) -> dict:
    # TODO: model choice per node (Mistral vs OpenAI-oss) is not decided yet.
    model = get_mistral_llm()

    decision_result = state["decision_result"]
    user_prompt = (
        f"Necessity check: {state['necessity_result'].model_dump_json()}\n"
        f"Decision: {decision_result.model_dump_json() if decision_result else 'null'}\n"
        f"Requirements: {[r.model_dump() for r in state['requirements']]}"
    )
    response = model.invoke([("system", SYSTEM_PROMPT), ("human", user_prompt)])
    return {"explanation": response.content}
