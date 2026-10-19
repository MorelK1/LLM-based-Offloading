
"""Deterministic validation and unit normalization
of LLM-extracted requirements.

Validation enforces the requirement semantics supported
by the current System Model:

- CPU and RAM: minimum resource requirements
  targeting individual services (gte).
- E2E latency: maximum delay requirements
  targeting application flows (lte).

Unsupported constraints are rejected rather than
silently coerced into supported semantics.

Only validated and normalized requirements are
forwarded to downstream decision modules.
"""

import math
from typing import Literal

from pydantic import BaseModel

from agent.model.schemas import ExtractedRequirement, Flow, Requirement, Service
from agent.utils.pipeline import CANONICAL_UNIT, to_native_unit

EXPECTED_TARGET = {
    "cpu": "service",
    "ram": "service",
    "latency": "flow",
}

EXPECTED_COMPARATOR = {
    "cpu": "gte",
    "ram": "gte",
    "latency": "lte",
}

RejectionReason = Literal[
    "unsupported_kpi",
    "invalid_target_type",
    "unsupported_comparator",
    "unknown_target",
    "invalid_source_span",
    "invalid_value",
    "invalid_unit",
]


class RejectedRequirement(BaseModel):
    """One extracted requirement that failed validation, with why -- never
    assigned a requirement_id, since ids are only handed out to survivors."""

    requirement: ExtractedRequirement
    reason: RejectionReason


def validate_and_normalize(
    extracted_requirements: list[ExtractedRequirement],
    intent_text: str,
    services: dict[str, Service],
    flows: dict[str, Flow],
) -> tuple[list[Requirement], list[RejectedRequirement]]:
    """Validates each extracted requirement against the system's actual
    semantics, converts its target_value to the KPI's canonical unit (see
    to_native_unit), and assigns a deterministic requirement_id to every
    survivor -- the same "drop rather than guess" policy grounding already
    applies to an unresolved target, but with a recorded reason instead of a
    silent drop.

    Checked, in order (first failure wins, no partial credit):
    1. kpi_type is one of the three supported KPIs.
    2. target_type matches what that KPI targets (cpu/ram -> service,
       latency -> flow).
    3. comparator matches EXPECTED_COMPARATOR for that KPI.
    4. target_id actually exists in the application context.
    5. source_span is a non-empty, exact substring of intent_text.
    6. target_value is finite and positive.
    7. (unit, kpi_type) is a recognized pairing -- see to_native_unit.

    Returns (requirements, rejected): requirements are ready for every
    downstream node (already normalized, already carry a requirement_id);
    rejected carries each failure's own requirement and reason, for
    diagnostics -- never silently discarded.
    """
    accepted: list[ExtractedRequirement] = []
    rejected: list[RejectedRequirement] = []

    for req in extracted_requirements:
        reason: RejectionReason | None = None

        if req.kpi_type not in EXPECTED_TARGET:
            reason = "unsupported_kpi"
        elif req.target_type != EXPECTED_TARGET[req.kpi_type]:
            reason = "invalid_target_type"
        elif req.comparator != EXPECTED_COMPARATOR[req.kpi_type]:
            reason = "unsupported_comparator"
        elif req.target_id not in (services if req.target_type == "service" else flows):
            reason = "unknown_target"
        elif not req.source_span or req.source_span not in intent_text:
            reason = "invalid_source_span"
        elif not math.isfinite(req.target_value) or req.target_value <= 0:
            reason = "invalid_value"

        native_value = None
        if reason is None:
            native_value = to_native_unit(req.target_value, req.unit, req.kpi_type)
            if native_value is None:
                reason = "invalid_unit"

        if reason is not None:
            rejected.append(RejectedRequirement(requirement=req, reason=reason))
            continue

        accepted.append(req.model_copy(update={
            "target_value": native_value,
            "unit": CANONICAL_UNIT[req.kpi_type],
        }))

    requirements = [
        Requirement(requirement_id=f"req-{i:03d}", **req.model_dump())
        for i, req in enumerate(accepted, start=1)
    ]

    return requirements, rejected
