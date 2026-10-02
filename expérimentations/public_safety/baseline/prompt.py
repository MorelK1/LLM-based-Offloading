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
- Each requirement you extract targets exactly one target: a service (for "cpu"/"ram") \
or a flow (for "latency"), never a node. Set its target_type accordingly and target_id \
to the matching service_id/flow_id from the provided lists.
- An intent may state more than one requirement at once (e.g. "needs at least 12 vCPU \
and 24GB of RAM" states two: a cpu one and a ram one, both targeting the same service). \
Extract one entry in requirements per explicit numeric threshold stated in the intent -- \
never merge several thresholds into one entry, never drop one because another is \
present. For each, quote the exact excerpt expressing it as source_span.
- Each new requirement you extract REPLACES its target's existing baseline for that \
exact KPI -- every other requirement (every other service's/flow's own baseline, and \
any other KPI of the same service/flow not mentioned in this intent) stays unchanged \
and must still be satisfied in whatever placement you propose."""

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

Finding a valid new placement is a search over the WHOLE configuration, not just over \
where to put the one service whose requirement changed: moving it calls the placement \
of every OTHER service into question too, even ones that violated nothing themselves \
-- a node you move a service onto may now be overfull for someone already there, or a \
neighbor that didn't move may lose its link to the one that did. When that happens, it \
does not mean no solution exists -- it means the best placement requires moving those \
other services as well. Keep adjusting the FULL placement, moving as many services as \
needed, until you find one where rules 1-3 hold for every service and every flow at \
once.

Decision procedure:
- If the CURRENT placement already satisfies every new requirement and rules 1-3 for \
every service and flow -> outcome="STAY", new_placement = the current placement, \
unchanged.
- Else, if some OTHER full placement (you may move any number of services) satisfies \
every new requirement and rules 1-3 everywhere -> outcome="OFFLOAD". Among every \
placement that satisfies everything, the BEST one -- the one you must return as \
new_placement -- is defined by this exact order: (1) the one that moves the FEWEST \
services away from their current_node, compared to every other valid placement, not \
just "fewer than naively moving everything"; (2) only if several valid placements tie \
on that same minimal number of moves, prefer the one with the lowest total tier cost \
(iot=0, edge=1, fog=2, cloud=3, summed over every service's node). Do not settle for \
the first valid placement you find -- keep searching until you're confident no valid \
placement moves fewer services.
- Else (no placement satisfies everything) -> outcome="INFEASIBLE", new_placement = \
the current placement, unchanged (nothing should move since nothing would fix it).

Only extract a requirement entry when the intent states an explicit numeric threshold \
on a target that is in the provided lists -- but extract EVERY such threshold the \
intent states, as its own entry in requirements. new_placement must list every \
service_id exactly once, each mapped to a node_id from the provided list.

Respond with a single JSON object with exactly these fields: requirements (a list of \
objects, each with target_type, target_id, kpi_type, comparator, target_value, unit, \
source_span), outcome, new_placement, explanation -- see the examples below for the \
exact shape (omitted in zero-shot mode, in which case follow this field list \
precisely)."""

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
  "requirements": [
    {{
      "target_type": "service", "target_id": "V1", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 3, "unit": "vCPU", "source_span": "at least 3 vCPU"
    }}
  ],
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
  "requirements": [
    {
      "target_type": "service", "target_id": "V3", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 5, "unit": "vCPU", "source_span": "at least 5 vCPU"
    }
  ],
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
  "requirements": [
    {
      "target_type": "flow", "target_id": "P1", "kpi_type": "latency", "comparator": "lte",
      "target_value": 15, "unit": "ms", "source_span": "within 15 ms end-to-end"
    }
  ],
  "outcome": "INFEASIBLE",
  "new_placement": {"V1": "edge_C", "V2": "edge_C", "V4": "edge_C"},
  "explanation": "processing_delay alone = wcet(V1) + wcet(V2) + wcet(V4) = 8 + 12 + 3 = 23ms, already above the 15ms budget. This does not depend on placement at all (co-locating everything only removes communication_delay, which is already 0 here), so no placement can ever satisfy this budget. Nothing should move."
}"""

_EXAMPLE_MULTI_REQUIREMENT = """Example (OFFLOAD, compound intent -- two requirements extracted from one \
sentence) -- same application, a different infrastructure instance:

Infrastructure nodes:
- edge_D (tier=edge): cpu_cores=4, ram_gb=8
- cloud_D (tier=cloud): cpu_cores=32, ram_gb=64

Infrastructure links:
- edge_D <-> cloud_D: bandwidth_mbps=50, latency_ms=10

Application services:
- V1: Vehicle Detection Service (Detects vehicles in the live camera feed) | current_node=edge_D | requirements={"cpu_cores": 2, "ram_gb": 4} | wcet_ms=None | output_size=None
- V2: License Plate Recognition Service (Reads plate numbers from detected vehicles) | current_node=edge_D | requirements={"cpu_cores": 1, "ram_gb": 2} | wcet_ms=None | output_size=None
- V4: Alert Dispatch Service (Sends alerts to traffic control) | current_node=cloud_D | requirements={"cpu_cores": 1, "ram_gb": 1} | wcet_ms=None | output_size=None

Application flows:
- P1: License Plate Alert Path | path=V1 -> V2 -> V4 | baseline latency budget=None

User intent:
"The Vehicle Detection Service has been upgraded and now needs at least 4 vCPU and at least 6GB of RAM to run."

Correct output (this is exactly the JSON shape you must produce every time -- note TWO entries in \
requirements, one per threshold, both targeting V1):
{
  "requirements": [
    {
      "target_type": "service", "target_id": "V1", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 4, "unit": "vCPU", "source_span": "at least 4 vCPU"
    },
    {
      "target_type": "service", "target_id": "V1", "kpi_type": "ram", "comparator": "gte",
      "target_value": 6, "unit": "GB", "source_span": "at least 6GB of RAM"
    }
  ],
  "outcome": "OFFLOAD",
  "new_placement": {"V1": "cloud_D", "V2": "edge_D", "V4": "cloud_D"},
  "explanation": "On edge_D, V1 co-located with V2 (1 vCPU, 2GB): available = 4-1=3 vCPU and 8-2=6GB, which satisfies the RAM floor but not the 4 vCPU floor. Moving V1 alone to cloud_D: co-located there with V4 (1 vCPU, 1GB), available = 32-1=31 vCPU and 64-1=63GB, satisfying both new thresholds at once."
}"""

_EXAMPLE_RIPPLE = """Example (OFFLOAD, ripple effect -- moving the targeted service for capacity \
breaks connectivity for an untouched neighbor, which must then move too) -- same application, a \
partially-connected infrastructure instance (NOT every pair of nodes has a direct link):

Infrastructure nodes:
- edge_E (tier=edge): cpu_cores=4, ram_gb=8
- fog_E (tier=fog): cpu_cores=8, ram_gb=16
- cloud_E (tier=cloud): cpu_cores=32, ram_gb=64

Infrastructure links:
- edge_E <-> fog_E: bandwidth_mbps=50, latency_ms=8
- fog_E <-> cloud_E: bandwidth_mbps=50, latency_ms=20
(no direct link between edge_E and cloud_E -- multi-hop routing is not supported)

Application services:
- V1: Vehicle Detection Service (Detects vehicles in the live camera feed) | current_node=edge_E | requirements={"cpu_cores": 2, "ram_gb": 4} | wcet_ms=None | output_size=None
- V2: License Plate Recognition Service (Reads plate numbers from detected vehicles) | current_node=fog_E | requirements={"cpu_cores": 2, "ram_gb": 4} | wcet_ms=None | output_size=None
- V3: Congestion Analysis Service (Estimates traffic density from the feed) | current_node=fog_E | requirements={"cpu_cores": 3, "ram_gb": 6} | wcet_ms=None | output_size=None
- V4: Alert Dispatch Service (Sends alerts to traffic control) | current_node=cloud_E | requirements={"cpu_cores": 1, "ram_gb": 1} | wcet_ms=None | output_size=None

Application flows:
- P1: License Plate Alert Path | path=V1 -> V2 -> V4 | baseline latency budget=None

User intent:
"The License Plate Recognition Service now needs at least 8 vCPU to run a heavier model."

Correct output (this is exactly the JSON shape you must produce every time -- note TWO services \
moved, V2 for its own requirement and V1 only because V2 moving away broke V1's connectivity):
{
  "requirements": [
    {
      "target_type": "service", "target_id": "V2", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 8, "unit": "vCPU", "source_span": "at least 8 vCPU"
    }
  ],
  "outcome": "OFFLOAD",
  "new_placement": {"V1": "fog_E", "V2": "cloud_E", "V3": "fog_E", "V4": "cloud_E"},
  "explanation": "On fog_E, V2 shares the node with V3 (3 vCPU): available = 8 - 3 = 5, below the required 8, so V2 cannot stay. The only node with enough free capacity is cloud_E (32 vCPU, only V4 there). Moving V2 alone to cloud_E would leave V1 on edge_E -- but edge_E has no direct link to cloud_E, so V1->V2 would be disconnected. So V1 must move too: edge_E <-> fog_E is a direct link, and fog_E has room for V1 (2 vCPU) alongside V3 (3 vCPU), available = 8 - 3 - 2 = 3, still non-negative. Final placement: V1 and V3 co-located on fog_E, V2 and V4 co-located on cloud_E, fog_E <-> cloud_E is a direct link so V1->V2 stays connected, and V2->V4 is co-located."
}"""

ONE_SHOT_SYSTEM_PROMPT = "{base}\n\nHere is an example:\n\n{example}".format(
    base=ZERO_SHOT_SYSTEM_PROMPT, example=_EXAMPLE_STAY
)

FEW_SHOT_SYSTEM_PROMPT = (
    "{base}\n\nHere are some examples:\n\n{ex1}\n\n{ex2}\n\n{ex3}\n\n{ex4}\n\n{ex5}".format(
        base=ZERO_SHOT_SYSTEM_PROMPT,
        ex1=_EXAMPLE_STAY, ex2=_EXAMPLE_OFFLOAD, ex3=_EXAMPLE_INFEASIBLE,
        ex4=_EXAMPLE_MULTI_REQUIREMENT, ex5=_EXAMPLE_RIPPLE,
    )
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
