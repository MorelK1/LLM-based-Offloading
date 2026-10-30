"""Prompt for the single-LLM-call "direct" baseline, targeting eval/'s
ARVR-flavored system model (workload_mi + node.mips, output_size in Mb,
fixed_placement) -- NOT a port of expérimentations/public_safety/baseline/
prompt.py's text, because that one's RULES describe a model that no longer
matches agent/utils/pipeline.py:

- processing_delay there is "sum of wcet_ms (else 0)" -- eval's services
  never set wcet_ms, so that text would tell the model processing delay is
  always zero, while verifier.py (reusing the real, current
  service_processing_delay_ms) actually computes a nonzero, placement-
  dependent delay from workload_mi/node.mips. Rewritten below to match.
- communication_delay there is "ceil(output_size / bandwidth_mbps)", with no
  propagation_delay_ms and no *1000 (s->ms) conversion -- stale relative to
  the current shortest_path_delays_ms (Mb/bandwidth_mbps * 1000 +
  propagation_delay_ms, summed over the cheapest multi-hop path, not just a
  direct link). Rewritten below to match.
- a separate "Connectivity" rule (direct link required) no longer exists:
  decision_engine_cp_sat.py's own docstring says connectivity is "no longer
  a modeled requirement in its own right" -- multi-hop routing prices it in,
  and the only hard failure is a genuinely disconnected graph. Dropped below.
- its OFFLOAD tie-break ("fewest moves, then lowest total tier cost") is
  also stale: decision_engine_cp_sat.py's objective minimizes disruption
  ALONE -- "[t]ies ... are not broken by anything". Rewritten below to not
  assert a tie-break rule that doesn't exist.
- fixed_placement (C1/C5 pinning in eval's services.json) didn't exist when
  that prompt was written at all -- added below as a new hard rule.

"Direct" (as opposed to the sibling cot/ variant): the model must output
ONLY the final JSON, no reasoning text before/after it -- explanation is the
LAST field of the schema, requested as a post-hoc justification of an
already-decided answer, not a scratchpad used to arrive at it. Whether a
model can actually solve the placement search this implies without a
visible scratchpad depends on whether it has its own internal/hidden
reasoning mode enabled (OpenRouter's reasoning/reasoning_effort/
include_reasoning params) -- a model-level mechanism, unrelated to whether
THIS prompt itself is CoT-style (it isn't: no visible chain of thought is
requested or allowed).
"""

from agent.model.schemas import Flow, Link, Node, Service

_ROLE = """You are an expert in intent-driven service placement and \
resource optimization in Cloud–Edge–IoT environments. \
You help operators interpret evolving application requirements\
and determine appropriate service reconfigurations."""

_GLOSSARY = """Definitions:
- A service is a task with a static baseline resource footprint (cpu_cores in vCPU, \
ram_gb in GB) it reserves on whichever node currently hosts it ("current_node"). A \
flow is a named, ordered chain of services (service_id -> service_id -> ...) \
representing one end-to-end dataflow, with its own baseline latency budget (in ms).
- A service declare workload_mi (its execution workload, in millions of \
instructions) and/or output_size_mb (the data volume it emits per invocation, in \
megabits), used by the Latency rule below. A node may declare mips \
(its effective processing rate, in millions of instructions/second)
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
Extract one entry in requirements per explicit numeric threshold stated in the intent -- \
never merge several thresholds into one entry, never drop one because another is \
present. For each, quote the exact excerpt expressing it as source_span.
- Each new requirement you extract REPLACES its target's existing baseline for that \
exact KPI -- every other requirement (every other service's/flow's own baseline, and \
any other KPI of the same service/flow not mentioned in this intent) stays unchanged \
and must still be satisfied in whatever placement you propose.
- Report each requirement's unit exactly as the intent itself states it -- e.g. "500 \
millicores" -> unit="millicore", "2048 MiB" -> unit="MiB" -- never convert it yourself \
when filling the requirements list. Supported units, by kpi_type:
  - cpu: vCPU, CPU, core, cores (1:1 with vCPU), millicore, mCPU, m (0.001 vCPU each).
  - ram: KB, MB, GB, TB (decimal: 1e-6, 1e-3, 1, 1e3 GB) -- or KiB, MiB, GiB, TiB \
(binary, powers of 1024: 1 MiB = 2^20/1e9 ≈ 0.0010486 GB, NOT the same as 1e-3 GB; \
same distinction applies to KiB/GiB/TiB).
  - latency: ms, µs, us, s, seconds (1, 0.001, 0.001, 1000, 1000 ms each).
  Every cpu_cores/ram_gb capacity and every latency budget given to you below is \
ALREADY expressed in the canonical unit (vCPU / GB / ms). Before you compare a \
requirement's target_value against any of them to decide feasibility, convert it to \
that canonical unit yourself using the factors above -- only the `unit` field you \
report back in requirements stays in the intent's original wording; every internal \
feasibility comparison you make must use the converted, canonical value."""

_RULES = """Feasibility rules -- apply these exactly, they define whether a placement \
is valid:
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

Finding a valid new placement is a search over the WHOLE configuration, not just over \
where to put the one service whose requirement changed: moving it calls the placement \
of every OTHER (non-fixed) service into question too, even ones that violated nothing \
themselves -- a node you move a service onto may now be overfull for someone already \
there. When that happens, it does not mean no solution exists -- it means the best \
placement requires moving those other services as well. Keep adjusting the FULL \
placement, moving as many non-fixed services as needed, until you find one where rules \
1-3 hold for every service and every flow at once.

Decision procedure:
- If the CURRENT placement already satisfies every new requirement and rules 1-3 for \
every service and flow -> outcome="STAY", new_placement = the current placement, \
unchanged.
- Else, if some OTHER full placement (you may move any number of non-fixed services) \
satisfies every new requirement and rules 1-3 everywhere -> outcome="OFFLOAD". Among \
every placement that satisfies everything, the BEST one -- the one you must return as \
new_placement -- is the one that moves the FEWEST services away from their \
current_node, compared to every other valid placement, not just "fewer than naively \
moving everything". If several valid placements tie on that same minimal number of \
moves, any one of them is an acceptable answer -- there is no secondary preference \
(no tier-cost or other tie-break) to apply. Do not settle for the first valid placement \
you find -- keep searching until you're confident no valid placement moves fewer \
services.
- Else (no placement satisfies everything, including because a fixed_placement service \
itself cannot be given what it needs without moving it) -> outcome="INFEASIBLE", \
new_placement = the current placement, unchanged (nothing should move since nothing \
would fix it).

Only extract a requirement entry when the intent states an explicit numeric threshold \
on a target that is in the provided lists -- but extract EVERY such threshold the \
intent states, as its own entry in requirements. new_placement must list every \
service_id exactly once, each mapped to a node_id from the provided list.

Respond with a single JSON object with exactly these fields: requirements (a list of \
objects, each with target_type, target_id, kpi_type, comparator, target_value, unit, \
source_span), outcome, new_placement, explanation -- see the examples below for the \
exact shape (omitted in zero-shot mode, in which case follow this field list \
precisely). Output ONLY that JSON object -- no markdown code fence (no ``` anywhere), \
no commentary before or after it, nothing but the raw JSON text itself."""

ZERO_SHOT_SYSTEM_PROMPT = "{role}\n\n{glossary}\n\n{rules}".format(
    role=_ROLE, glossary=_GLOSSARY, rules=_RULES
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

Correct output (this is exactly the JSON shape you must produce every time):
{{
  "requirements": [
    {{
      "target_type": "service", "target_id": "C1", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 3, "unit": "vCPU", "source_span": "at least 3 vCPU"
    }}
  ],
  "outcome": "STAY",
  "new_placement": {{"C1": "edge_A", "C2": "edge_A", "C3": "cloud_A"}},
  "explanation": "On edge_A, C1 is co-located with C2, whose footprint is 1 vCPU. Available capacity = 8 - 1 = 7, which already satisfies the new requirement of at least 3 vCPU, so nothing needs to move."
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
    {
      "target_type": "service", "target_id": "C2", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 5, "unit": "vCPU", "source_span": "at least 5 vCPU"
    }
  ],
  "outcome": "OFFLOAD",
  "new_placement": {"C1": "edge_B", "C2": "cloud_B", "C3": "cloud_B"},
  "explanation": "On edge_B, C2's only neighbor is C1 (2 vCPU). Available capacity = 6 - 2 = 4, below the required 5, so C2 cannot stay. Moving C2 alone to cloud_B: only C3 (1 vCPU) is there, available = 48 - 1 = 47, which satisfies the requirement -- only the one service that actually needed to move was moved."
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

Correct output (this is exactly the JSON shape you must produce every time):
{
  "requirements": [
    {
      "target_type": "service", "target_id": "C2", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 9, "unit": "vCPU", "source_span": "at least 9 vCPU"
    }
  ],
  "outcome": "INFEASIBLE",
  "new_placement": {"C1": "edge_C", "C2": "edge_C", "C3": "cloud_C"},
  "explanation": "C2 alone would need at least 9 vCPU, but the largest node, cloud_C, only has 6 vCPU of total capacity -- even hosted completely alone there, with every other service moved elsewhere, C2 could never fit. This is a ceiling on C2's own node, so no placement of the other services changes it. Nothing should move."
}"""

_EXAMPLE_MULTI_REQUIREMENT = """Example (OFFLOAD, compound intent -- two requirements extracted from one \
sentence) -- same application, a different infrastructure instance:

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

Correct output (this is exactly the JSON shape you must produce every time -- note TWO entries in \
requirements, one per threshold, both targeting C1):
{
  "requirements": [
    {
      "target_type": "service", "target_id": "C1", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 4, "unit": "vCPU", "source_span": "at least 4 vCPU"
    },
    {
      "target_type": "service", "target_id": "C1", "kpi_type": "ram", "comparator": "gte",
      "target_value": 6, "unit": "GB", "source_span": "at least 6GB of RAM"
    }
  ],
  "outcome": "OFFLOAD",
  "new_placement": {"C1": "cloud_D", "C2": "edge_D", "C3": "cloud_D"},
  "explanation": "On edge_D, C1 co-located with C2 (1 vCPU, 2GB): available = 4-1=3 vCPU and 8-2=6GB. The RAM floor (6GB) is met but the 4 vCPU floor is not. Moving C1 alone to cloud_D: co-located there with C3 (1 vCPU, 1GB), available = 32-1=31 vCPU and 64-1=63GB, satisfying both new thresholds at once."
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
    {
      "target_type": "service", "target_id": "C1", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 4, "unit": "vCPU", "source_span": "at least 4 vCPU"
    }
  ],
  "outcome": "OFFLOAD",
  "new_placement": {"C1": "iot_E", "C2": "edge_E", "C3": "edge_E"},
  "explanation": "C1 has fixed_placement=True, so it must stay on iot_E no matter what. With C2 (1 vCPU) also on iot_E, available capacity there is 4 - 1 = 3, below the 4 vCPU C1 now needs -- and C1 itself can never move to solve this. So C2 must move instead, freeing all of iot_E's 4 vCPU for C1 alone. Moving C2 to edge_E (already hosting C3, 1 vCPU): available = 6 - 1 = 5, which comfortably fits C2's own 1 vCPU footprint."
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
feasibility comparison inside explanation uses the converted canonical values):
{
  "requirements": [
    {
      "target_type": "service", "target_id": "C2", "kpi_type": "cpu", "comparator": "gte",
      "target_value": 3500, "unit": "millicore", "source_span": "3500 millicores"
    },
    {
      "target_type": "service", "target_id": "C2", "kpi_type": "ram", "comparator": "gte",
      "target_value": 3072, "unit": "MiB", "source_span": "3072 MiB of RAM"
    }
  ],
  "outcome": "OFFLOAD",
  "new_placement": {"C1": "edge_F", "C2": "cloud_F", "C3": "cloud_F"},
  "explanation": "Converted to canonical units: 3500 millicores = 3500 * 0.001 = 3.5 vCPU, and 3072 MiB = 3072 * 2^20/1e9 ≈ 3.221 GB. On edge_F, C2 co-located with C1 (1 vCPU, 2GB): available = 4-1=3 vCPU, below the required 3.5 vCPU, so C2 cannot stay (the 3.221GB RAM floor alone would have been met: 8-2=6GB available, but the CPU floor is not). Moving C2 alone to cloud_F: co-located with C3 (1 vCPU, 1GB), available = 32-1=31 vCPU and 64-1=63GB, both comfortably satisfying the converted requirements."
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
