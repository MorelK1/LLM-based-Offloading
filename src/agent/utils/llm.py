"""Chat model retrieval (NVIDIA models via the official LangChain integration).

`ChatNVIDIA` targets the NVIDIA API Catalog (build.nvidia.com), compatible with
the LangChain/LangGraph ecosystem. The API key is read automatically from the
NVIDIA_API_KEY environment variable (.env).
"""

from langchain_nvidia_ai_endpoints import ChatNVIDIA

from agent.utils.config import LLMConfig


def get_llm(config: LLMConfig) -> ChatNVIDIA:
    return ChatNVIDIA(
        model=config.model,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
