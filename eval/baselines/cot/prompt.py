"""Prompt for the single-LLM-call "CoT" baseline -- same task, same domain
rules as the sibling direct-llm/prompt.py, but the model is explicitly asked
to work through its reasoning BEFORE committing to an answer, instead of
only justifying one after the fact.

Design choice: the reasoning trace lives INSIDE the structured output, as
several named fields produced BEFORE decision/placement, rather than one
big freeform scratchpad field or free text before a separate JSON block --
_RULES below spells out six steps (requirement identification, current-
placement verification, feasibility assessment, migration minimization,
final decision, explanation), and the three steps that precede the final
decision each leave a trace in the output itself: `requirements` (step 1),
`verification.current_placement_feasible`/`violated_requirements` (steps
2-3), `migration_count` (step 4). `justification` (step 6) is the only
free-text field, and it is brief and post-hoc -- the actual working is
the structured fields before it, not this one. Reasons for this shape
(distributed structured fields rather than one `reasoning` blob):
1. Every other LLM call in this project (intent_grounding_node,
   explanation_node, and direct-llm's own baseline) uses
   with_structured_output against a single Pydantic schema -- splitting
   "freeform reasoning text" from "a JSON block" would need its own
   brittle parser (where does the reasoning end and the JSON begin?) that
   nothing else here needs.
2. Autoregressive generation still gets the real CoT effect either way:
   what matters is that `requirements`/`verification`/`migration_count`
   are generated BEFORE `decision`/`placement` in the token stream, so the
   model cannot have already silently committed to an answer before
   working through them -- field ORDER in the schema, not the free-text/
   JSON boundary or a single named field, is what makes this a scratchpad
   rather than (direct-llm's) post-hoc justification.
3. If this file's design is instead meant to be true freeform text before a
   separate JSON block -- a deliberately different mechanism from the above
   (e.g. to test whether an explicit code-fence split changes a model's
   behavior) -- that's a one-line change to the final instruction
   paragraph below, not a rewrite of GLOSSARY, which is unchanged domain
   facts shared with direct-llm/prompt.py (see that file's own docstring
   for why THEIR content differs from
   expérimentations/public_safety/baseline/prompt.py).

GLOSSARY below is intentionally near-identical to "direct llm"/prompt.py's
-- the feasibility model (capacity, latency via workload_mi/node.mips +
Mb/propagation_delay_ms communication delay, fixed_placement, unit
conversion) is a fact about the task, unaffected by whether the model
reasons visibly or not. _RULES and the output schema (see schema.py) are
this baseline's own, richer than direct-llm's -- not a mirror of it.
"""

from agent.model.schemas import Flow, Link, Node, Service

_ROLE = """You are a service orchestration decision-maker for a Cloud-Edge computing environment."""

_TASK = """
Given: \
- An intent that specifies new requirements for one or more services or flows \
- The application and its components \
- The infrastructure and network characteristics \
- The current service placement \
- The user requirements \
- The system constraints \

Your task is to determine whether the current placement satisfies all requirements and to propose a new placement if necessary.
"""

_GLOSSARY = """Definitions:
- A service is a task with a static baseline resource footprint (cpu_cores in vCPU, \
ram_gb in GB) it reserves on whichever node currently hosts it ("current_node"). A \
flow is a named, ordered chain of services (service_id -> service_id -> ...) \
representing one end-to-end dataflow, with its own baseline latency budget (in ms).
- A service may also declare workload_mi (its execution workload, in millions of \
instructions) and/or output_size_mb (the data volume it emits per invocation, in \
megabits), used by the Latency rule below. A node may declare mips (its effective \
processing rate, in millions of instructions/second).
- fixed_placement=True means this service's current_node is PERMANENT: it must appear \
unchanged in new_placement no matter what, in every case (STAY, OFFLOAD, INFEASIBLE). \
It is never counted as "moved" and must never be chosen as the service that moves to \
fix some OTHER service's or flow's requirement -- if capacity needs to be freed around \
it, a different, non-fixed co-located service must move instead.
- Each requirement you extract targets exactly one target: a service (for "cpu"/"ram") \
or a flow (for "latency"), never a node. Set its target_type accordingly and target_id \
to the matching service_id/flow_id from the provided lists. kpi_type is always exactly \
one of the three words "cpu", "ram", or "latency" -- NEVER the internal field names \
shown in the services list ("cpu_cores", "ram_gb"); those describe the data you're \
given, they are not values you ever write into kpi_type yourself.
- An intent may state more than one requirement at once (e.g. "needs at least 12 vCPU \
and 24GB of RAM" states two: a cpu one and a ram one, both targeting the same service). \
- Each new requirement you extract REPLACES its target's existing baseline for that \
exact KPI -- every other requirement (every other service's/flow's own baseline, and \
any other KPI of the same service/flow not mentioned in this intent) stays unchanged \
and must still be satisfied in whatever placement you propose.
- These are the constraints: \
1. Capacity: for every node, the SUM of the (possibly-replaced) footprint of every \
service placed there must not exceed that node's cpu_cores / ram_gb capacity.
2. Latency: for every flow with a latency budget (its own baseline, or the new target \
if this intent is about that flow), total_latency = processing_delay + \
communication_delay must stay within that budget.
   - processing_delay = sum, over every service along the flow's path, of that \
service's own processing delay under wherever IT ends up placed: workload_mi / \
(hosting node's mips) * 1000 (ms) if both the service's workload_mi and the hosting \
node's mips are declared; 0 if either is missing. This is placement-DEPENDENT -- \
moving a service to a node with a different mips changes its own processing delay.
   - communication_delay, summed over every consecutive pair of services in the flow: \
0 if both end up co-located on the same node; otherwise the cost of the CHEAPEST path \
through the infrastructure links between their two nodes (not necessarily a direct \
link -- multi-hop routing through intermediate nodes is allowed and priced normally), \
where each link traversed on that path costs (upstream service's output_size_mb / \
link's bandwidth_mbps) * 1000 (0 if the upstream service has no declared output_size_mb) \
plus that link's own propagation_delay_ms. If no path at all connects the two nodes \
(the infrastructure graph is disconnected between them), that placement is invalid for \
this flow, regardless of everything else.
3. Fixed placement: any service with fixed_placement=True must keep its current_node \
in new_placement, always, in STAY, OFFLOAD, and INFEASIBLE alike. It may never be the \
service you move to satisfy a requirement, even its own -- if ITS requirement can't be \
satisfied without it moving, the correct outcome is INFEASIBLE, not moving it anyway.
"""

_RULES = """Perform a structured, step-by-step analysis before producing the final decision. \

Step 1 — Requirement Identification \
Identify every requirement expressed in the user intent. \
For each requirement, determine: \
- Target component or application flow \
- Metric (cpu | ram | latency) \
- Comparison operator \
- Threshold value and unit \

Step 2 — Current Placement Verification
Evaluate the current placement against all identified requirements and system constraints. \

Determine which requirements are satisfied and which are violated. \

Step 3 — Feasibility Assessment
If the current placement violates some requirements, assess whether an alternative feasible placement exists. \

Consider: \
- Node resource capacities \
- Service placement constraints \
- Service dependencies \
- Network links \
- End-to-end latency constraints \

Step 4 — Migration Minimization
If a feasible alternative exists, select a placement that minimizes the number of relocated components. \

The migration count is the number of components whose assigned node differs from the current placement. \

Step 5 — Final Decision
Return exactly one decision:

STAY:
The current placement satisfies all requirements.

OFFLOAD:
The current placement violates at least one requirement,
but a feasible alternative placement exists.

INFEASIBLE:
No feasible placement satisfies all requirements.



STEP 6 — Explanation Generation

Provide a concise, factual explanation indicating:
- Why the current placement can or cannot be preserved.
- Which components are migrated, when applicable.
- How the decision addresses the updated requirements.

Return a valid JSON object:

{
  "requirements": [
    {
      "target": "...",
      "metric": "...",
      "operator": "...",
      "value": 0,
      "unit": "..."
    }
  ],
  "verification": {
    "current_placement_feasible": true,
    "violated_requirements": [
      {
        "target": "...",
        "metric": "...",
        "reason": "..."
      }
    ]
  },
  "decision": "STAY | OFFLOAD | INFEASIBLE",
  "placement": {
    "component_id": "node_id"
  },
  "migration_count": 0,
  "justification": "Brief explanation of the decision."
}

For STAY, return the current placement unchanged. \
For OFFLOAD, return the complete updated placement. \
For INFEASIBLE, return "placement": null.

Return only the JSON object.

"""



ZERO_SHOT_SYSTEM_PROMPT = "{role}\n\n{task}\n\n{glossary}\n\n{rules}".format(
    role=_ROLE, task=_TASK, glossary=_GLOSSARY, rules=_RULES
)

_EXAMPLE_APP = """Infrastructure nodes:
- edge_A (tier=edge): cpu_cores=8, ram_gb=16, mips=4000
- cloud_A (tier=cloud): cpu_cores=64, ram_gb=128, mips=20000

Infrastructure links:
- edge_A <-> cloud_A: bandwidth_mbps=100, propagation_delay_ms=15

Application services:
- C1: Capture Service (Captures the live camera feed) | current_node=edge_A | requirements={"cpu_cores": 2, "ram_gb": 4} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C2: Recognition Service (Detects objects in the feed) | current_node=edge_A | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C3: Rendering Service (Overlays recognition results onto the view) | current_node=cloud_A | requirements={"cpu_cores": 1, "ram_gb": 1} | fixed_placement=False | workload_mi=None | output_size_mb=None

Application flows:
- P1: Recognition Path | path=C1 -> C2 -> C3 | baseline latency budget=None"""

_EXAMPLE_STAY = """Example (STAY) -- same fictional "AR Capture Pipeline" application used in every \
example below, just a different infrastructure instance each time:

{app}

User intent:
"The Capture Service now needs at least 3 vCPU to handle a higher-resolution camera."

Correct output (this is exactly the JSON shape you must produce every time -- note \
`requirements`/`verification` come BEFORE `decision`/`placement`, so the feasibility check is \
worked out before the answer, not after):
{{
  "requirements": [
    {{"target": "C1", "metric": "cpu", "operator": "gte", "value": 3, "unit": "vCPU"}}
  ],
  "verification": {{
    "current_placement_feasible": true,
    "violated_requirements": []
  }},
  "decision": "STAY",
  "placement": {{"C1": "edge_A", "C2": "edge_A", "C3": "cloud_A"}},
  "migration_count": 0,
  "justification": "On edge_A, C1 is co-located with C2, whose footprint is 1 vCPU. Available capacity = 8 - 1 = 7, which already satisfies the new requirement of at least 3 vCPU, so nothing needs to move."
}}""".format(app=_EXAMPLE_APP)

_EXAMPLE_OFFLOAD = """Example (OFFLOAD) -- same application, a different infrastructure instance:

Infrastructure nodes:
- edge_B (tier=edge): cpu_cores=6, ram_gb=12, mips=3000
- cloud_B (tier=cloud): cpu_cores=48, ram_gb=96, mips=16000

Infrastructure links:
- edge_B <-> cloud_B: bandwidth_mbps=100, propagation_delay_ms=20

Application services:
- C1: Capture Service (Captures the live camera feed) | current_node=edge_B | requirements={"cpu_cores": 2, "ram_gb": 4} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C2: Recognition Service (Detects objects in the feed) | current_node=edge_B | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C3: Rendering Service (Overlays recognition results onto the view) | current_node=cloud_B | requirements={"cpu_cores": 1, "ram_gb": 1} | fixed_placement=False | workload_mi=None | output_size_mb=None

Application flows:
- P1: Recognition Path | path=C1 -> C2 -> C3 | baseline latency budget=None

User intent:
"The Recognition Service now requires at least 5 vCPU to run the upgraded detection model."

Correct output (this is exactly the JSON shape you must produce every time):
{
  "requirements": [
    {"target": "C2", "metric": "cpu", "operator": "gte", "value": 5, "unit": "vCPU"}
  ],
  "verification": {
    "current_placement_feasible": false,
    "violated_requirements": [
      {"target": "C2", "metric": "cpu", "reason": "requires >=5 vCPU, only 4 vCPU available on edge_B"}
    ]
  },
  "decision": "OFFLOAD",
  "placement": {"C1": "edge_B", "C2": "cloud_B", "C3": "cloud_B"},
  "migration_count": 1,
  "justification": "On edge_B, C2's only neighbor is C1 (2 vCPU). Available capacity = 6 - 2 = 4, below the required 5, so C2 cannot stay. Moving C2 alone to cloud_B: only C3 (1 vCPU) is there, available = 48 - 1 = 47, which satisfies the requirement -- only the one service that actually needed to move was moved."
}"""

_EXAMPLE_INFEASIBLE = """Example (INFEASIBLE) -- same application, a different infrastructure \
instance, and this time no placement at all can satisfy the requirement:

Infrastructure nodes:
- edge_C (tier=edge): cpu_cores=4, ram_gb=8, mips=2000
- cloud_C (tier=cloud): cpu_cores=6, ram_gb=12, mips=16000

Infrastructure links:
- edge_C <-> cloud_C: bandwidth_mbps=50, propagation_delay_ms=25

Application services:
- C1: Capture Service (Captures the live camera feed) | current_node=edge_C | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C2: Recognition Service (Detects objects in the feed) | current_node=edge_C | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C3: Rendering Service (Overlays recognition results onto the view) | current_node=cloud_C | requirements={"cpu_cores": 1, "ram_gb": 1} | fixed_placement=False | workload_mi=None | output_size_mb=None

Application flows:
- P1: Recognition Path | path=C1 -> C2 -> C3 | baseline latency budget=None

User intent:
"The Recognition Service must now be provisioned with at least 9 vCPU to run a much larger model."

Correct output (this is exactly the JSON shape you must produce every time -- note `placement` \
is null for INFEASIBLE, nothing is applied since nothing would fix it):
{
  "requirements": [
    {"target": "C2", "metric": "cpu", "operator": "gte", "value": 9, "unit": "vCPU"}
  ],
  "verification": {
    "current_placement_feasible": false,
    "violated_requirements": [
      {"target": "C2", "metric": "cpu", "reason": "requires >=9 vCPU, only 3 vCPU available on edge_C, and no node in the infrastructure has 9 vCPU of total capacity"}
    ]
  },
  "decision": "INFEASIBLE",
  "placement": null,
  "migration_count": 0,
  "justification": "C2 alone would need at least 9 vCPU, but the largest node, cloud_C, only has 6 vCPU of total capacity -- even hosted completely alone there, with every other service moved elsewhere, C2 could never fit. This is a ceiling on C2's own node, so no placement of the other services changes it. Nothing should move."
}"""

_EXAMPLE_MULTI_REQUIREMENT = """Example (OFFLOAD, compound intent -- two thresholds stated at once on the \
same service) -- same application, a different infrastructure instance:

Infrastructure nodes:
- edge_D (tier=edge): cpu_cores=4, ram_gb=8, mips=2000
- cloud_D (tier=cloud): cpu_cores=32, ram_gb=64, mips=16000

Infrastructure links:
- edge_D <-> cloud_D: bandwidth_mbps=100, propagation_delay_ms=10

Application services:
- C1: Capture Service (Captures the live camera feed) | current_node=edge_D | requirements={"cpu_cores": 2, "ram_gb": 4} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C2: Recognition Service (Detects objects in the feed) | current_node=edge_D | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C3: Rendering Service (Overlays recognition results onto the view) | current_node=cloud_D | requirements={"cpu_cores": 1, "ram_gb": 1} | fixed_placement=False | workload_mi=None | output_size_mb=None

Application flows:
- P1: Recognition Path | path=C1 -> C2 -> C3 | baseline latency budget=None

User intent:
"The Capture Service has been upgraded and now needs at least 4 vCPU and at least 6GB of RAM to run."

Correct output (this is exactly the JSON shape you must produce every time -- note BOTH stated \
thresholds, cpu and ram, must hold at once on whichever node C1 ends up on):
{
  "requirements": [
    {"target": "C1", "metric": "cpu", "operator": "gte", "value": 4, "unit": "vCPU"},
    {"target": "C1", "metric": "ram", "operator": "gte", "value": 6, "unit": "GB"}
  ],
  "verification": {
    "current_placement_feasible": false,
    "violated_requirements": [
      {"target": "C1", "metric": "cpu", "reason": "requires >=4 vCPU, only 3 vCPU available on edge_D (the 6GB RAM floor is met, 6GB available)"}
    ]
  },
  "decision": "OFFLOAD",
  "placement": {"C1": "cloud_D", "C2": "edge_D", "C3": "cloud_D"},
  "migration_count": 1,
  "justification": "On edge_D, C1 co-located with C2 (1 vCPU, 2GB): available = 4-1=3 vCPU and 8-2=6GB. The RAM floor (6GB) is met but the 4 vCPU floor is not. Moving C1 alone to cloud_D: co-located there with C3 (1 vCPU, 1GB), available = 32-1=31 vCPU and 64-1=63GB, satisfying both new thresholds at once."
}"""

_EXAMPLE_FIXED_PLACEMENT = """Example (OFFLOAD, fixed_placement -- the service whose requirement \
changed can never move itself, so a co-located NEIGHBOR must move instead to free up its room) -- \
same application, a different infrastructure instance:

Infrastructure nodes:
- iot_E (tier=iot): cpu_cores=4, ram_gb=8, mips=1000
- edge_E (tier=edge): cpu_cores=6, ram_gb=12, mips=3000

Infrastructure links:
- iot_E <-> edge_E: bandwidth_mbps=100, propagation_delay_ms=5

Application services:
- C1: Capture Service (Captures the live camera feed, physically wired to this sensor) | current_node=iot_E | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=True | workload_mi=None | output_size_mb=None
- C2: Recognition Service (Detects objects in the feed) | current_node=iot_E | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C3: Rendering Service (Overlays recognition results onto the view) | current_node=edge_E | requirements={"cpu_cores": 1, "ram_gb": 1} | fixed_placement=False | workload_mi=None | output_size_mb=None

Application flows:
- P1: Recognition Path | path=C1 -> C2 -> C3 | baseline latency budget=None

User intent:
"The Capture Service now needs at least 4 vCPU to keep up with the new sensor."

Correct output (this is exactly the JSON shape you must produce every time -- note C1 itself never \
moves, even though it's the one whose requirement changed; C2 moves instead):
{
  "requirements": [
    {"target": "C1", "metric": "cpu", "operator": "gte", "value": 4, "unit": "vCPU"}
  ],
  "verification": {
    "current_placement_feasible": false,
    "violated_requirements": [
      {"target": "C1", "metric": "cpu", "reason": "requires >=4 vCPU, only 3 vCPU available on iot_E -- C1 itself has fixed_placement=True and cannot move to fix this"}
    ]
  },
  "decision": "OFFLOAD",
  "placement": {"C1": "iot_E", "C2": "edge_E", "C3": "edge_E"},
  "migration_count": 1,
  "justification": "C1 has fixed_placement=True, so it must stay on iot_E no matter what. With C2 (1 vCPU) also on iot_E, available capacity there is 4 - 1 = 3, below the 4 vCPU C1 now needs -- and C1 itself can never move to solve this. So C2 must move instead, freeing all of iot_E's 4 vCPU for C1 alone. Moving C2 to edge_E (already hosting C3, 1 vCPU): available = 6 - 1 = 5, which comfortably fits C2's own 1 vCPU footprint."
}"""

_EXAMPLE_UNIT_CONVERSION = """Example (OFFLOAD, non-canonical units -- the intent states millicores and \
MiB, NOT vCPU/GB) -- same application, a different infrastructure instance:

Infrastructure nodes:
- edge_F (tier=edge): cpu_cores=4, ram_gb=8, mips=2000
- cloud_F (tier=cloud): cpu_cores=32, ram_gb=64, mips=16000

Infrastructure links:
- edge_F <-> cloud_F: bandwidth_mbps=100, propagation_delay_ms=12

Application services:
- C1: Capture Service (Captures the live camera feed) | current_node=edge_F | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C2: Recognition Service (Detects objects in the feed) | current_node=edge_F | requirements={"cpu_cores": 1, "ram_gb": 2} | fixed_placement=False | workload_mi=None | output_size_mb=None
- C3: Rendering Service (Overlays recognition results onto the view) | current_node=cloud_F | requirements={"cpu_cores": 1, "ram_gb": 1} | fixed_placement=False | workload_mi=None | output_size_mb=None

Application flows:
- P1: Recognition Path | path=C1 -> C2 -> C3 | baseline latency budget=None

User intent:
"Bump the Recognition Service to 3500 millicores and 3072 MiB of RAM."

Correct output (this is exactly the JSON shape you must produce every time -- note the \
reported unit stays "millicore"/"MiB", exactly as the intent said it, even though the \
feasibility check (verification, justification) uses the converted canonical values):
{
  "requirements": [
    {"target": "C2", "metric": "cpu", "operator": "gte", "value": 3500, "unit": "millicore"},
    {"target": "C2", "metric": "ram", "operator": "gte", "value": 3072, "unit": "MiB"}
  ],
  "verification": {
    "current_placement_feasible": false,
    "violated_requirements": [
      {"target": "C2", "metric": "cpu", "reason": "requires >=3.5 vCPU (3500 millicores), only 3 vCPU available on edge_F (the ~3.221GB RAM floor is met, 6GB available)"}
    ]
  },
  "decision": "OFFLOAD",
  "placement": {"C1": "edge_F", "C2": "cloud_F", "C3": "cloud_F"},
  "migration_count": 1,
  "justification": "Converted to canonical units: 3500 millicores = 3.5 vCPU, and 3072 MiB ≈ 3.221 GB. On edge_F, C2 co-located with C1 (1 vCPU, 2GB): available = 4-1=3 vCPU, below the required 3.5 vCPU, so C2 cannot stay. Moving C2 alone to cloud_F: co-located with C3 (1 vCPU, 1GB), available = 32-1=31 vCPU and 64-1=63GB, both comfortably satisfying the converted requirements."
}"""

ONE_SHOT_SYSTEM_PROMPT = "{base}\n\nHere is an example:\n\n{example}".format(
    base=ZERO_SHOT_SYSTEM_PROMPT, example=_EXAMPLE_STAY
)

FEW_SHOT_SYSTEM_PROMPT = (
    "{base}\n\nHere are some examples:\n\n{ex1}\n\n{ex2}\n\n{ex3}\n\n{ex4}\n\n{ex5}\n\n{ex6}".format(
        base=ZERO_SHOT_SYSTEM_PROMPT,
        ex1=_EXAMPLE_STAY, ex2=_EXAMPLE_OFFLOAD, ex3=_EXAMPLE_INFEASIBLE,
        ex4=_EXAMPLE_MULTI_REQUIREMENT, ex5=_EXAMPLE_FIXED_PLACEMENT, ex6=_EXAMPLE_UNIT_CONVERSION,
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
        f"- {n.node_id} (tier={n.tier}): cpu_cores={n.cpu_cores}, ram_gb={n.ram_gb}, mips={n.mips}"
        for n in nodes.values()
    )
    links_desc = "\n".join(
        f"- {link.source_node} <-> {link.target_node}: bandwidth_mbps={link.bandwidth_mbps}, "
        f"propagation_delay_ms={link.propagation_delay_ms}"
        for link in links
    )
    services_desc = "\n".join(
        f"- {s.service_id}: {s.name} ({s.description}) | current_node={s.current_node} | "
        f"requirements={s.requirements} | fixed_placement={s.fixed_placement} | "
        f"workload_mi={s.workload_mi} | output_size_mb={s.output_size}"
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
