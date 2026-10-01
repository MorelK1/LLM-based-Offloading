import os

from agent.utils.llm_openrouter import get_openrouter_gpt_llm


def test_model_override_takes_precedence_over_env_var(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "env/default-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    llm = get_openrouter_gpt_llm("override/explicit-model")

    assert llm.model_name == "override/explicit-model"


def test_falls_back_to_env_var_when_no_override_given(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "env/default-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    llm = get_openrouter_gpt_llm()

    assert llm.model_name == "env/default-model"
