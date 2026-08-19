"""Configuration loading (config.yaml + environment variables)."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")


class LLMConfig(BaseModel):
    base_url: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 1024


class DataConfig(BaseModel):
    nodes_csv: str
    links_csv: str
    app_state_json: str


class ScenarioConfig(BaseModel):
    end_to_end_latency_ms: int


class AppConfig(BaseModel):
    llm: LLMConfig
    data: DataConfig
    scenario: ScenarioConfig


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or PROJECT_ROOT / "config" / "config.yaml"
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    model = os.environ.get("LLM_MODEL")
    if not model:
        raise RuntimeError("LLM_MODEL is missing from the environment (.env)")
    raw["llm"]["model"] = model

    return AppConfig(**raw)
