"""Prompts for the Intent Grounding node (structured requirement extraction)."""

from agent.model.schemas import Service

SYSTEM_PROMPT = """You are a requirement extractor for a service offloading \
system in the Cloud Continuum. Given a user intent in natural language and \
the list of application services, extract the expressed resource \
requirements and return ONLY a JSON array, with no additional text. \
Each item must follow this schema:
{
  "requirement_id": "req-XXX",
  "kpi_type": "cpu" | "ram" | "latency" | ...,
  "comparator": "gte" | "lte" | "eq",
  "target_value": <number>,
  "unit": "vCPU" | "GB" | "ms" | ...,
  "service": "<service_id>",
  "source_span": "<exact excerpt from the source text>"
}
"""


def build_user_prompt(intent_text: str, services: dict[str, Service]) -> str:
    services_desc = "\n".join(
        f"- {s.service_id}: {s.name} ({s.description})" for s in services.values()
    )
    return (
        f"Application services:\n{services_desc}\n\n"
        f"User intent:\n\"{intent_text}\""
    )
