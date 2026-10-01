"""Prompt for the single-LLM-call baseline.

The feasibility rules below are a precise restatement of what our real
engine actually checks (agent/utils/pipeline.py: capacity_satisfied,
latency_satisfied, flow_latency_ms, check_connectivity) -- not a simplified
or strawman version. Scoring independently re-verifies the LLM's proposed
placement against those same real functions (see verifier.py), so the
prompt needs to describe the real rules accurately for the comparison to be
fair.
"""

from agent.model.schemas import Flow, Link, Node, Service

_ROLE = """You are a complete intent-based service offloading decision system for the \
Cloud Continuum. Unlike a staged pipeline (separate extraction, feasibility-check, and \
solver steps), you must do everything yourself in a single response: identify what the \
user's intent targets, extract it as a structured requirement, determine whether the \
current placement already satisfies it, and -- if not -- find a full alternative \
placement that satisfies the new requirement AND every other service's/flow's existing \
baseline requirement at the same time, or conclude that no such placement exists."""

_GLOSSARY = """Definitions:
- A service is a task with a static baseline resource footprint (cpu_cores in vCPU, \
ram_gb in GB) it reserves on whichever node currently hosts it ("current_node"). A \
flow is a named, ordered chain of services (service_id -> service_id -> ...) \
representing one end-to-end dataflow, with its own baseline latency budget (in ms).
- Every requirement targets exactly one target: a service (for "cpu"/"ram") or a flow \
(for "latency"), never a node. Set target_type accordingly and target_id to the \
matching service_id/flow_id from the provided lists.
- The new requirement you extract REPLACES that one target's baseline for its exact \
KPI -- every other service's/flow's own baseline requirement stays unchanged and must \
still be satisfied in whatever placement you propose."""

_RULES = """Feasibility rules -- apply these exactly, they define whether a placement \
is valid:
1. Capacity: for every node, the SUM of the (possibly-replaced) footprint of every \
service placed there must not exceed that node's cpu_cores / ram_gb capacity.
2. Latency: for every flow with a latency budget (its own baseline, or the new target \
if this intent is about that flow), total_latency = processing_delay + \
communication_delay must stay within that budget.
   - processing_delay = sum of each service's wcet_ms (if given, else 0) for every \
service along the flow's path.
   - communication_delay, per consecutive hop in the flow: 0 if both services end up \
co-located on the same node; otherwise, if the upstream service has a declared \
output_size, ceil(output_size / link_bandwidth_mbps); otherwise the link's static \
latency_ms (if the link lists one).
3. Connectivity: two consecutive services in a flow must be co-located on the same \
node, or hosted on two directly linked nodes -- never on two nodes with no link \
between them.

Decision procedure:
- If the CURRENT placement already satisfies the new requirement and rules 1-3 for \
every service and flow -> outcome="STAY", new_placement = the current placement, \
unchanged.
- Else, if some OTHER full placement (you may move any number of services) satisfies \
the new requirement and rules 1-3 everywhere -> outcome="OFFLOAD", new_placement = \
that placement (prefer moving as few services as possible if several valid options \
exist, but any one genuinely valid placement is acceptable).
- Else (no placement satisfies everything) -> outcome="INFEASIBLE", new_placement = \
the current placement, unchanged (nothing should move since nothing would fix it).

Only extract a requirement when the intent states an explicit numeric threshold on a \
target that is in the provided lists. new_placement must list every service_id \
exactly once, each mapped to a node_id from the provided list.

Respond with a single JSON object with exactly these fields: target_type, target_id, \
kpi_type, comparator, target_value, unit, outcome, new_placement, explanation -- see \
the examples below for the exact shape (omitted in zero-shot mode, in which case \
follow this field list precisely)."""

ZERO_SHOT_SYSTEM_PROMPT = "{role}\n\n{glossary}\n\n{rules}".format(
    role=_ROLE, glossary=_GLOSSARY, rules=_RULES
)

_EXAMPLE_APP = """Infrastructure nodes:
- edge_A (tier=edge): cpu_cores=6, ram_gb=12
- cloud_A (tier=cloud): cpu_cores=40, ram_gb=80

Infrastructure links:
- edge_A <-> cloud_A: bandwidth_mbps=50, latency_ms=10

Application services:
- V1: Vehicle Detection Service (Detects vehicles in the live camera feed) | current_node=edge_A | requirements={"cpu_cores": 2, "ram_gb": 4} | wcet_ms=None | output_size=None
- V2: License Plate Recognition Service (Reads plate numbers from detected vehicles) | current_node=edge_A | requirements={"cpu_cores": 1, "ram_gb": 2} | wcet_ms=None | output_size=None
- V3: Congestion Analysis Service (Estimates traffic density from the feed) | current_node=cloud_A | requirements={"cpu_cores": 2, "ram_gb": 4} | wcet_ms=None | output_size=None
- V4: Alert Dispatch Service (Sends alerts to traffic control) | current_node=cloud_A | requirements={"cpu_cores": 1, "ram_gb": 1} | wcet_ms=None | output_size=None

Application flows:
- P1: License Plate Alert Path | path=V1 -> V2 -> V4 | baseline latency budget=None
- P2: Congestion Alert Path | path=V1 -> V3 -> V4 | baseline latency budget=None"""

_EXAMPLE_STAY = """Example (STAY) -- same fictional "Smart Traffic Monitoring" application used in every \
example below, just a different infrastructure instance each time (exactly like public_safety's own \
samples: one fixed application, many infrastructure instances):

{app}

User intent:
"The Vehicle Detection Service now needs at least 3 vCPU to keep up with higher camera resolution."

Correct output (this is exactly the JSON shape you must produce every time):
{{
  "target_type": "service",
  "target_id": "V1",
  "kpi_type": "cpu",
  "comparator": "gte",
  "target_value": 3,
  "unit": "vCPU",
  "outcome": "STAY",
  "new_placement": {{"V1": "edge_A", "V2": "edge_A", "V3": "cloud_A", "V4": "cloud_A"}},
  "explanation": "On edge_A, V1 is co-located with V2, whose footprint is 1 vCPU. Available capacity = 6 - 1 = 5, which already satisfies the new requirement of at least 3 vCPU, so nothing needs to move."
}}""".format(app=_EXAMPLE_APP)

_EXAMPLE_OFFLOAD = """Example (OFFLOAD) -- same application, a different infrastructure instance:

Infrastructure nodes:
- edge_B (tier=edge): cpu_cores=4, ram_gb=8
- cloud_B (tier=cloud): cpu_cores=32, ram_gb=64

Infrastructure links:
- edge_B <-> cloud_B: bandwidth_mbps=50, latency_ms=15

Application services:
- V1: Vehicle Detection Service (Detects vehicles in the live camera feed) | current_node=edge_B | requirements={"cpu_cores": 2, "ram_gb": 4} | wcet_ms=None | output_size=None
- V2: License Plate Recognition Service (Reads plate numbers from detected vehicles) | current_node=edge_B | requirements={"cpu_cores": 1, "ram_gb": 2} | wcet_ms=None | output_size=None
- V3: Congestion Analysis Service (Estimates traffic density from the feed) | current_node=edge_B | requirements={"cpu_cores": 1, "ram_gb": 2} | wcet_ms=None | output_size=None
- V4: Alert Dispatch Service (Sends alerts to traffic control) | current_node=cloud_B | requirements={"cpu_cores": 1, "ram_gb": 1} | wcet_ms=None | output_size=None

Application flows:
- P1: License Plate Alert Path | path=V1 -> V2 -> V4 | baseline latency budget=None
- P2: Congestion Alert Path | path=V1 -> V3 -> V4 | baseline latency budget=None

User intent:
"The Congestion Analysis Service now requires at least 5 vCPU to run the upgraded traffic model."

Correct output (this is exactly the JSON shape you must produce every time):
{
  "target_type": "service",
  "target_id": "V3",
  "kpi_type": "cpu",
  "comparator": "gte",
  "target_value": 5,
  "unit": "vCPU",
  "outcome": "OFFLOAD",
  "new_placement": {"V1": "edge_B", "V2": "edge_B", "V3": "cloud_B", "V4": "cloud_B"},
  "explanation": "On edge_B, V3's other co-located services are V1 (2 vCPU) and V2 (1 vCPU). Available capacity = 4 - 3 = 1, which is below the required 5, so staying is not possible. Moving V3 alone to cloud_B: only V4 (1 vCPU) is there, available = 32 - 1 = 31, which satisfies the requirement -- only the one service that actually needed to move was moved."
}"""

_EXAMPLE_INFEASIBLE = """Example (INFEASIBLE) -- same application, a different infrastructure instance, \
and this time the new requirement targets a FLOW, not a service:

Infrastructure nodes:
- edge_C (tier=edge): cpu_cores=4, ram_gb=8
- cloud_C (tier=cloud): cpu_cores=16, ram_gb=32

Infrastructure links:
- edge_C <-> cloud_C: bandwidth_mbps=20, latency_ms=25

Application services:
- V1: Vehicle Detection Service (Detects vehicles in the live camera feed) | current_node=edge_C | requirements={"cpu_cores": 1, "ram_gb": 2} | wcet_ms=8 | output_size=None
- V2: License Plate Recognition Service (Reads plate numbers from detected vehicles) | current_node=edge_C | requirements={"cpu_cores": 1, "ram_gb": 2} | wcet_ms=12 | output_size=None
- V4: Alert Dispatch Service (Sends alerts to traffic control) | current_node=edge_C | requirements={"cpu_cores": 1, "ram_gb": 1} | wcet_ms=3 | output_size=None

Application flows:
- P1: License Plate Alert Path | path=V1 -> V2 -> V4 | baseline latency budget=30ms

User intent:
"The License Plate Alert Path must now complete within 15 ms end-to-end."

Correct output (this is exactly the JSON shape you must produce every time):
{
  "target_type": "flow",
  "target_id": "P1",
  "kpi_type": "latency",
  "comparator": "lte",
  "target_value": 15,
  "unit": "ms",
  "outcome": "INFEASIBLE",
  "new_placement": {"V1": "edge_C", "V2": "edge_C", "V4": "edge_C"},
  "explanation": "processing_delay alone = wcet(V1) + wcet(V2) + wcet(V4) = 8 + 12 + 3 = 23ms, already above the 15ms budget. This does not depend on placement at all (co-locating everything only removes communication_delay, which is already 0 here), so no placement can ever satisfy this budget. Nothing should move."
}"""

ONE_SHOT_SYSTEM_PROMPT = "{base}\n\nHere is an example:\n\n{example}".format(
    base=ZERO_SHOT_SYSTEM_PROMPT, example=_EXAMPLE_STAY
)

FEW_SHOT_SYSTEM_PROMPT = "{base}\n\nHere are some examples:\n\n{ex1}\n\n{ex2}\n\n{ex3}".format(
    base=ZERO_SHOT_SYSTEM_PROMPT, ex1=_EXAMPLE_STAY, ex2=_EXAMPLE_OFFLOAD, ex3=_EXAMPLE_INFEASIBLE
)

PROMPT_STRATEGIES = {
    "zero_shot": ZERO_SHOT_SYSTEM_PROMPT,
    "one_shot": ONE_SHOT_SYSTEM_PROMPT,
    "few_shot": FEW_SHOT_SYSTEM_PROMPT,
}
DEFAULT_PROMPT_STRATEGY = "zero_shot"


def build_user_prompt(
    intent_text: str,
    services: dict[str, Service],
    flows: dict[str, Flow],
    nodes: dict[str, Node],
    links: list[Link],
) -> str:
    nodes_desc = "\n".join(
        f"- {n.node_id} (tier={n.tier}): cpu_cores={n.cpu_cores}, ram_gb={n.ram_gb}"
        for n in nodes.values()
    )
    links_desc = "\n".join(
        f"- {link.source_node} <-> {link.target_node}: bandwidth_mbps={link.bandwidth_mbps}, "
        f"latency_ms={link.latency_ms}"
        for link in links
    )
    services_desc = "\n".join(
        f"- {s.service_id}: {s.name} ({s.description}) | current_node={s.current_node} | "
        f"requirements={s.requirements} | wcet_ms={s.wcet_ms} | output_size={s.output_size}"
        for s in services.values()
    )
    flows_desc = "\n".join(
        f"- {f.flow_id}: {f.name} | path={' -> '.join(f.path)} | "
        f"baseline latency budget={(f.requirements or {}).get('latency')}ms"
        for f in flows.values()
    )
    return (
        f"Infrastructure nodes:\n{nodes_desc}\n\n"
        f"Infrastructure links:\n{links_desc}\n\n"
        f"Application services:\n{services_desc}\n\n"
        f"Application flows:\n{flows_desc}\n\n"
        f"User intent:\n\"{intent_text}\""
    )
