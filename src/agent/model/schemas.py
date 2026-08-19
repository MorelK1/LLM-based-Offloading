"""Domain schemas shared across the pipeline."""

from typing import Literal

from pydantic import BaseModel


class Node(BaseModel):
    node_id: str
    node_name: str
    tier: Literal["iot", "edge", "fog", "cloud"]
    node_type: str
    cpu_cores: int
    cpu_freq_ghz: float
    ram_gb: int
    storage_gb: int
    mobility: Literal["static", "mobile"]


class Link(BaseModel):
    link_id: str
    source_node: str
    target_node: str
    link_type: str
    bandwidth_mbps: int
    latency_ms: float
    packet_loss_rate: float
    reliability: float


class Service(BaseModel):
    service_id: str
    name: str
    description: str
    current_node: str
    requirements: dict[str, float] | None = None


class Requirement(BaseModel):
    """Structured requirement extracted from a natural-language intent."""

    requirement_id: str
    kpi_type: str  # e.g. "cpu", "ram", "latency"
    comparator: Literal["gte", "lte", "eq"]
    target_value: float
    unit: str
    service: str
    source_span: str


class NecessityCheckResult(BaseModel):
    status: Literal["reconfiguration_required", "no_action_needed"]
    violated_requirements: list[str]
    services_to_reconsider: list[str]


class DecisionResult(BaseModel):
    decision: dict[str, str]  # service_id -> new node_id
    eligible_nodes_considered: list[str]
    requirements_satisfied: list[str]
    new_configuration: dict[str, str]  # service_id -> node_id (full state)
