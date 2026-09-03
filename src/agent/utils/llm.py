"""Chat model retrieval (NVIDIA models via the official LangChain integration).

Two NVIDIA-hosted models are available for this project, each exposed through
its own environment variable so callers can fetch the one they need:
- MISTRAL_MODEL (e.g. mistralai/mistral-nemotron)
- OPENAI_MODEL   (e.g. openai/gpt-oss-120b)

"""

import os
import time
from typing import Any

from dotenv import find_dotenv, load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_nvidia_ai_endpoints import ChatNVIDIA

load_dotenv(find_dotenv())

_DEFAULT_TEMPERATURE = 0
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
        timeout=120,
        # reasoning_effort = "low",
    )


def get_mistral_llm() -> BaseChatModel:
    return _build_chat_model("MISTRAL_MODEL")


def get_openai_llm() -> BaseChatModel:
    return _build_chat_model("OPENAI_MODEL")

def get_meta_llm() -> BaseChatModel:
    return _build_chat_model("META_MODEL")

def get_nvidia_llm() -> BaseChatModel:
    return _build_chat_model("NVIDIA_MODEL")


# def invoke_with_retry(
#     runnable: Runnable,
#     input: Any,
#     max_attempts: int = 3,
#     backoff_seconds: float = 2.0,
# ) -> Any:
#     """Invoke a runnable (e.g. a `with_structured_output` chain), retrying on
#     failure with exponential backoff.

#     NVIDIA's guided-JSON structured output is flaky for some models (transient
#     500s / read timeouts even though plain chat completions succeed), so
#     structured-output calls need a retry to be usable in practice.
#     """
#     last_error: Exception | None = None
#     for attempt in range(1, max_attempts + 1):
#         try:
#             return runnable.invoke(input)
#         except Exception as exc:  # noqa: BLE001 - retrying on any transient failure
#             last_error = exc
#             if attempt < max_attempts:
#                 time.sleep(backoff_seconds * 2 ** (attempt - 1))
#     raise last_error
