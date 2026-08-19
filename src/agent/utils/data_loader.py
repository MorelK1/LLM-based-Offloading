"""Loading of the infrastructure (nodes/links) and the application state."""

import json
from pathlib import Path

import pandas as pd

from agent.model.schemas import Link, Node, Service


def load_nodes(csv_path: str | Path) -> dict[str, Node]:
    df = pd.read_csv(csv_path)
    return {row.node_id: Node(**row._asdict()) for row in df.itertuples(index=False)}


def load_links(csv_path: str | Path) -> list[Link]:
    df = pd.read_csv(csv_path)
    return [Link(**row._asdict()) for row in df.itertuples(index=False)]


def load_services(json_path: str | Path) -> dict[str, Service]:
    with open(json_path) as f:
        raw = json.load(f)
    services = raw["application_context"]["services"]
    return {s["service_id"]: Service(**s) for s in services}
