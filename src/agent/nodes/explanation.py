"""LangGraph node: Trace & Explanation Generation."""

from agent.prompts.explanation import SYSTEM_PROMPT, build_user_prompt
from agent.states.state import AgentState
from agent.utils.llm_openrouter import get_openrouter_gpt_llm


def explanation_node(state: AgentState) -> dict:
    # OpenRouter (openai/gpt-5.4-mini), same choice as intent_grounding_node:
    # NVIDIA API Catalog's inference backend (get_mistral_llm) proved too
    # unreliable in practice -- see testbench / README.
    model = get_openrouter_gpt_llm()

    user_prompt = build_user_prompt(
        state["intent_text"],
        state["requirements"],
        state["necessity_result"],
        state["decision_result"],
    )
    response = model.invoke([("system", SYSTEM_PROMPT), ("human", user_prompt)])
    return {"explanation": response.content}
