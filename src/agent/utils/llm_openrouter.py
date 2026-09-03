"""Chat model retrieval for OpenRouter-hosted models.

Kept separate from utils/llm.py (NVIDIA API Catalog / ChatNVIDIA) because the
underlying client differs: OpenRouter is reached through the OpenAI-compatible
langchain_openai.ChatOpenAI client, pointed at OpenRouter's base_url, rather
than ChatNVIDIA. Introduced to mitigate NVIDIA API Catalog's inference
backend instability -- OpenRouter routes each request across multiple
providers hosting the same model instead of a single backend.
"""

import os

from dotenv import find_dotenv, load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

load_dotenv(find_dotenv())

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_TEMPERATURE = 0
_DEFAULT_MAX_TOKENS = 4096


def _build_openrouter_chat_model(env_var: str) -> BaseChatModel:
    model = os.environ.get(env_var)
    if not model:
        raise RuntimeError(f"{env_var} is missing from the environment (.env)")
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is missing from the environment (.env)")

    return ChatOpenAI(
        model=model,
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url=_OPENROUTER_BASE_URL,
        temperature=_DEFAULT_TEMPERATURE,
        max_tokens=_DEFAULT_MAX_TOKENS,
        timeout=120,
    )


def get_openrouter_gpt_llm() -> BaseChatModel:
    return _build_openrouter_chat_model("OPENROUTER_MODEL")
