"""Structured output schema for the single-LLM-call baseline.

Unlike our modular pipeline (intent_grounding -> necessity_checker ->
decision_engine -> explanation, four separate steps), this baseline does
everything in ONE call: identify the target, extract the requirement,
decide STAY/OFFLOAD/INFEASIBLE, propose a full placement, and explain it.
"""

from typing import Literal

from pydantic import BaseModel, Field

from agent.model.schemas import KpiType, TargetType, Unit


class BaselineResult(BaseModel):
    target_type: TargetType = Field(description="Whether the requirement targets a service or a flow")
    target_id: str = Field(description="service_id or flow_id from the provided lists")
    kpi_type: KpiType = Field(description="KPI targeted by the requirement")
    comparator: Literal["gte", "lte", "eq"] = Field(description="Comparison operator applied to target_value")
    target_value: float = Field(description="Numeric threshold for the KPI")
    unit: Unit = Field(description="Unit of target_value")
    outcome: Literal["STAY", "OFFLOAD", "INFEASIBLE"] = Field(
        description="STAY if the current placement already satisfies the new requirement and every "
        "other service/flow's own baseline requirement; OFFLOAD if a different full placement does; "
        "INFEASIBLE if no placement satisfies everything simultaneously"
    )
    new_placement: dict[str, str] = Field(
        description="The full placement you propose: every service_id mapped to the node_id it should "
        "run on. For STAY, this must be identical to the current placement. For INFEASIBLE, return the "
        "current placement unchanged (nothing can fix it, so nothing should move)."
    )
    explanation: str = Field(description="Plain-language explanation of the decision and why")
