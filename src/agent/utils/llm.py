"""Chat model retrieval (NVIDIA models via the official LangChain integration).

Two NVIDIA-hosted models are available for this project, each exposed through
its own environment variable so callers can fetch the one they need:
- MISTRAL_MODEL (e.g. mistralai/mistral-nemotron)
- OPENAI_MODEL   (e.g. openai/gpt-oss-120b)

Both go through the NVIDIA API Catalog (build.nvidia.com) via `ChatNVIDIA`,
which is a `BaseChatModel` implementation -> callers can depend on the
provider-agnostic `BaseChatModel` interface without knowing it's NVIDIA under
the hood. NVIDIA_API_KEY is read from the environment and passed explicitly.
"""

import os

from dotenv import find_dotenv, load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_nvidia_ai_endpoints import ChatNVIDIA

load_dotenv(find_dotenv())

_DEFAULT_TEMPERATURE = 1
_DEFAULT_MAX_TOKENS = 4096


def _build_chat_model(env_var: str) -> BaseChatModel:
    model = os.environ.get(env_var)
    if not model:
        raise RuntimeError(f"{env_var} is missing from the environment (.env)")
    if not os.environ.get("NVIDIA_API_KEY"):
        raise RuntimeError("NVIDIA_API_KEY is missing from the environment (.env)")

    return ChatNVIDIA(
        model=model,
        api_key=os.environ.get("NVIDIA_API_KEY"),
        temperature=_DEFAULT_TEMPERATURE,
        max_tokens=_DEFAULT_MAX_TOKENS,
    )


def get_mistral_llm() -> BaseChatModel:
    return _build_chat_model("MISTRAL_MODEL")


def get_openai_llm() -> BaseChatModel:
    return _build_chat_model("OPENAI_MODEL")
