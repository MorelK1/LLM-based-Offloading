"""Structured output schema for the single-LLM-call baseline.

Unlike our modular pipeline (intent_grounding -> necessity_checker ->
decision_engine -> explanation, four separate steps), this baseline does
everything in ONE call: identify the target, extract the requirement,
decide STAY/OFFLOAD/INFEASIBLE, propose a full placement, and explain it.
"""

from typing import Literal

from pydantic import BaseModel, Field

from agent.model.schemas import ExtractedRequirement


class BaselineResult(BaseModel):
    # Reuses the real pipeline's own ExtractedRequirement shape (kpi_type,
    # comparator, target_value, unit, target_type, target_id, source_span)
    # so the two are field-for-field comparable later. A plain intent states
    # exactly one requirement; a compound one (e.g. "needs at least 12 vCPU
    # and 24GB of RAM") states several at once -- one entry per explicit
    # numeric threshold, not one entry per call.
    requirements: list[ExtractedRequirement] = Field(
        description="Every requirement explicitly stated in the intent -- one entry per distinct "
        "target+KPI threshold. A compound intent (e.g. both a CPU and a RAM threshold for the same "
        "service) produces more than one entry here, not one entry averaging/combining them."
    )
    outcome: Literal["STAY", "OFFLOAD", "INFEASIBLE"] = Field(
        description="STAY if the current placement already satisfies every new requirement and every "
        "other service/flow's own baseline requirement; OFFLOAD if a different full placement does; "
        "INFEASIBLE if no placement satisfies everything simultaneously"
    )
    new_placement: dict[str, str] = Field(
        description="The full placement you propose: every service_id mapped to the node_id it should "
        "run on. For STAY, this must be identical to the current placement. For INFEASIBLE, return the "
        "current placement unchanged (nothing can fix it, so nothing should move)."
    )
    explanation: str = Field(description="Plain-language explanation of the decision and why")
