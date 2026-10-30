"""Prompt for the single-LLM-call "CoT" baseline -- same task, same domain
rules as the sibling direct-llm/prompt.py, but the model is explicitly asked
to work through its reasoning BEFORE committing to an answer, instead of
only justifying one after the fact.

Design choice: the reasoning trace lives INSIDE the structured output, as
the FIRST field of the JSON object (reasoning, then requirements, outcome,
new_placement, explanation) -- not as free text before a separate JSON
block. Three reasons:
1. Every other LLM call in this project (intent_grounding_node,
   explanation_node, and direct-llm's own baseline) uses
   with_structured_output against a single Pydantic schema -- splitting
   "freeform reasoning text" from "a JSON block" would need its own
   brittle parser (where does the reasoning end and the JSON begin?) that
   nothing else here needs.
2. Autoregressive generation still gets the real CoT effect either way:
   what matters is that `reasoning` is generated BEFORE `outcome`/
   `new_placement` in the token stream, so the model cannot have already
   silently committed to an answer before writing it -- field ORDER in the
   schema, not the free-text/JSON boundary, is what makes this a scratchpad
   rather than (direct-llm's) post-hoc justification.
3. If this file's design is instead meant to be true freeform text before a
   separate JSON block -- a deliberately different mechanism from the above
   (e.g. to test whether an explicit code-fence split changes a model's
   behavior) -- that's a one-line change to the final instruction
   paragraph below, not a rewrite of GLOSSARY/_RULES, which are unchanged
   domain facts shared with direct-llm/prompt.py (see that file's own
   docstring for why THEIR content differs from
   expérimentations/public_safety/baseline/prompt.py).

GLOSSARY and _RULES below are intentionally near-identical to
"direct llm"/prompt.py's -- the feasibility model (capacity, latency via
workload_mi/node.mips + Mb/propagation_delay_ms communication delay,
fixed_placement, unit conversion) is a fact about the task, unaffected by
whether the model reasons visibly or not. Only _ROLE and the final output-
format paragraph differ, plus every example now carries a worked `reasoning`
field in addition to the post-hoc `explanation`.
"""

from agent.model.schemas import Flow, Link, Node, Service

_ROLE = """You are a complete intent-based service offloading decision system for the \
Cloud-Edge-IoT Continuum. Unlike a staged pipeline (separate extraction, feasibility-check, \
and solver steps), you must do everything yourself in a single response: identify what the \
user's intent targets, extract it as a structured requirement, determine whether the \
current placement already satisfies it, and -- if not -- find a full alternative \
placement that satisfies the new requirement AND every other service's/flow's existing \
baseline requirement at the same time, or conclude that no such placement exists.

Think through this step by step, out loud, in the `reasoning` field, BEFORE deciding on \
an outcome or a placement -- use it to actually work through the problem (try the \
current placement first, check it against every rule, and if it fails, try candidate \
alternatives one at a time, checking each one, until you find a valid placement or run \
out of reasonable candidates to try), not to restate a conclusion you already reached \
silently. Your requirements/outcome/new_placement must follow directly from what you \
worked out in `reasoning`, not be decided independently of it."""

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
that canonical unit yourself using the factors above (show this conversion explicitly \
in `reasoning`) -- only the `unit` field you report back in requirements stays in the \
intent's original wording; every internal feasibility comparison you make must use the \
converted, canonical value."""

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
1-3 hold for every service and every flow at once. Do this adjusting VISIBLY, inside \
`reasoning` -- try one candidate, check it against rules 1-3, and if it fails, say so \
and try the next one, rather than silently arriving at a final candidate.

PROCEDURE:
RULE 1 — Requirements Extraction and Grounding

Identify all updated requirements expressed in the intent.

For each requirement, identify:
- Target service or application flow.
- KPI and comparison operator.
- Requested value and unit, exactly as the intent states it.
- Corresponding entity in the System Model.

Resolve indirect component references using the application
context. Distinguish historical (baseline) requirements from
the updated ones this intent states.

Since you do everything in this one call, YOU are the one who
must convert each value to its KPI's canonical unit (vCPU /
GB / ms, see the unit-conversion factors above) before using it
in RULE 2/3's feasibility checks below -- do this conversion
explicitly in `reasoning`. This is separate from what you
REPORT: the `unit` field in requirements always stays in the
intent's own original wording (e.g. "millicore", "MiB"), never
the canonical one -- only your internal comparisons use the
converted value.

RULE 2 — Necessity Assessment

Evaluate the current placement P0 against the updated
requirements and existing system constraints, using the
canonical-unit values from RULE 1.

Check whether:
- Resource capacities (cpu_cores, ram_gb) are respected on every node.
- Fixed components remain on their designated nodes.
- Application flows satisfy their E2E latency budgets (processing_delay
  + communication_delay, per the Latency rule above -- this already
  accounts for multi-hop routing between any two nodes, so there is no
  separate connectivity check: the only way two services' nodes can be
  unreachable from each other is if no path at all connects them, which
  the Latency check itself catches).

If P0 satisfies all requirements, select STAY and preserve P0.

RULE 3 — Reconfiguration Decision

If P0 violates the updated requirements, identify an
alternative placement.

Consider every node in the provided Infrastructure nodes list
and its available capacity -- every node given to you is
already a valid hosting candidate for any non-fixed service, no
separate eligibility check is needed beyond that list.

Ensure that the new placement satisfies:
- CPU and RAM capacity constraints (canonical units, as in RULE 2).
- Fixed placement constraints (fixed_placement=True services never move).
- Application E2E latency requirements (multi-hop routing included, as in RULE 2).

Among every placement that satisfies everything, choose the one that
moves the FEWEST services away from their current_node, compared to
every other valid placement -- not just "fewer than naively moving
everything". Do not settle for the first valid placement you find --
keep searching until you're confident no valid placement moves fewer
services. If several valid placements tie on that same minimal number
of moves, any one of them is an acceptable answer -- there is no
secondary preference (no tier-cost or other tie-break) to apply.

If you determine that no feasible placement exists,
select INFEASIBLE.

RULE 4 — Consistency Verification

Review the proposed decision and placement against all
applicable constraints.

Check that the migrated component list matches the
difference between P0 and the proposed placement.

Do not claim that a constraint is satisfied without
supporting evidence from the System Model.

RULE 5 — Explanation Generation

Provide a concise, factual explanation indicating:
- Why the current placement can or cannot be preserved.
- Which components are migrated, when applicable.
- How the decision addresses the updated requirements.

Only extract a requirement entry when the intent states an explicit numeric threshold \
on a target that is in the provided lists -- but extract EVERY such threshold the \
intent states, as its own entry in requirements. new_placement must list every \
service_id exactly once, each mapped to a node_id from the provided list.

Respond with a single JSON object with exactly these fields, IN THIS ORDER: reasoning \
(a string -- your full step-by-step working, written BEFORE you decide the fields that \
follow it: what the intent targets, the requirement(s) you extract from it, whether the \
current placement already satisfies everything, and -- if not -- each candidate \
placement you tried and why it passed or failed, until you reach the one you commit \
to), requirements, outcome, new_placement, explanation (a short, final, human-readable \
summary of the decision -- distinct from `reasoning`: this one is for a reader who \
only wants the conclusion, not your working). See the examples below for the exact \
shape (omitted in zero-shot mode, in which case follow this field list precisely). \
Output ONLY that JSON object -- no markdown code fence (no ``` anywhere), no \
commentary before or after it, nothing but the raw JSON text itself; the reasoning \
belongs INSIDE the `reasoning` field, not outside the JSON."""

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

Correct output (this is exactly the JSON shape you must produce every time -- note \
`reasoning` comes FIRST, written as real working, not a restated conclusion):
{{
  "reasoning": "Extract the requirement: Capture Service C1 needs at least 3 vCPU -- a cpu requirement, unit vCPU (already canonical, no conversion needed), targeting C1. Check whether the CURRENT placement already satisfies it: C1 is on edge_A, co-located with C2 (1 vCPU). Available capacity on edge_A = 8 (node capacity) - 1 (C2's footprint) = 7 vCPU, which is already >= 3. C2 and C3 have no new requirement and nothing about their placement would change, so their own baselines still hold; P1 has no latency budget to check. Since the current placement already satisfies the new requirement and every other rule, no search for an alternative is needed.",
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
  "reasoning": "Extract: Recognition Service C2 needs at least 5 vCPU, unit vCPU, canonical. Check STAY first: C2 is on edge_B, co-located with C1 (2 vCPU). Available = 6 - 2 = 4 vCPU, below the required 5 -- STAY fails. Search for an alternative: try moving only C2, leaving C1 and C3 where they are. If C2 moves to cloud_B, it is co-located there with C3 (1 vCPU); available on cloud_B = 48 - 1 = 47 vCPU, which satisfies the requirement. Nothing else is disturbed: C1 alone on edge_B is trivially within capacity, and there's no latency budget on P1 to re-check. This candidate -- only C2 moved -- satisfies everything with exactly one move; since STAY (zero moves) already failed, one move is the minimum possible, so this is the answer.",
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
  "reasoning": "Extract: Recognition Service C2 needs at least 9 vCPU, canonical unit. Check STAY: C2 on edge_C with C1 (1 vCPU); available = 4 - 1 = 3, below 9, fails. Before trying individual candidate placements, check a stronger fact first: could ANY node ever host C2 alone, ignoring every other service entirely? edge_C's total capacity is 4 vCPU, cloud_C's is 6 vCPU -- both below the 9 vCPU C2 itself requires. Since C2's own requirement exceeds the total capacity of every single node in the infrastructure, no placement -- however the other services are arranged -- can ever give C2 enough room. This is a hard ceiling on C2's own hosting node, not something redistributing C1/C3 could fix, so there is no point enumerating further candidates.",
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
  "reasoning": "Extract two requirements from one sentence: C1 needs at least 4 vCPU (cpu) and at least 6GB of RAM (ram), both canonical units, both targeting C1. Check STAY: C1 on edge_D with C2 (1 vCPU, 2GB); available = 4-1=3 vCPU (below 4, fails) and 8-2=6GB (meets 6 exactly, ok). The cpu floor alone fails, so STAY fails even though the ram floor would have passed on its own -- both must hold, not just one. Search: move C1 alone to cloud_D, co-located with C3 (1 vCPU, 1GB); available = 32-1=31 vCPU and 64-1=63GB, both thresholds satisfied simultaneously. One move; STAY (zero moves) already failed, so this is minimal.",
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
  "reasoning": "Extract: Capture Service C1 needs at least 4 vCPU, canonical unit. C1 has fixed_placement=True, so it must remain on iot_E regardless of outcome -- it is not a candidate to move, even though it's the service whose requirement changed. Check STAY: C1 co-located with C2 (1 vCPU) on iot_E; available = 4-1=3 vCPU, below the required 4 -- STAY fails. Since C1 cannot move, the only way to free capacity on iot_E is to move a different, non-fixed co-located service: C2. Try moving C2 to edge_E, co-located there with C3 (1 vCPU); available on edge_E = 6-1=5 vCPU, which comfortably fits C2's own 1 vCPU footprint. Re-check iot_E, now hosting only C1: available = 4-0=4 vCPU, exactly meeting the requirement. This candidate -- C2 moved, C1 untouched as required -- satisfies everything with the minimum possible disruption, since C1 was never eligible to be the one that moves.",
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
reported unit stays "millicore"/"MiB", exactly as the intent said it, even though \
`reasoning` works in the converted canonical values):
{
  "reasoning": "Extract two requirements: C2 needs at least 3500 millicores (cpu, reported unit stays 'millicore') and at least 3072 MiB of RAM (ram, reported unit stays 'MiB'), both targeting C2. Convert to canonical units before comparing against any node's capacity: 3500 millicores * 0.001 = 3.5 vCPU; 3072 MiB * 2^20/1e9 ≈ 3.221 GB. Check STAY: C2 co-located with C1 (1 vCPU, 2GB) on edge_F; available = 4-1=3 vCPU (below 3.5, fails) and 8-2=6GB (above 3.221, ok). The cpu floor fails, so STAY fails despite the ram floor passing on its own. Search: move C2 alone to cloud_F, co-located with C3 (1 vCPU, 1GB); available = 32-1=31 vCPU (above 3.5, ok) and 64-1=63GB (above 3.221, ok) -- both converted thresholds satisfied. One move; STAY already failed, so minimal.",
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
  "explanation": "Converted to canonical units: 3500 millicores = 3.5 vCPU, and 3072 MiB ≈ 3.221 GB. On edge_F, C2 co-located with C1 (1 vCPU, 2GB): available = 4-1=3 vCPU, below the required 3.5 vCPU, so C2 cannot stay. Moving C2 alone to cloud_F: co-located with C3 (1 vCPU, 1GB), available = 32-1=31 vCPU and 64-1=63GB, both comfortably satisfying the converted requirements."
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
