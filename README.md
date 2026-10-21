# Intent-Based Service Offloading in the Cloud Continuum

Implementation of the pipeline described (Intent Grounding →
Necessity Checker → Decision Engine → Trace & Explanation Generation) as a
**LangGraph** graph, on the "real-time video analysis" running example
(scenario 1).

The LLM nodes (`intent_grounding`, `explanation`) default to **OpenRouter**
(`openai/gpt-5.4-mini`) via `langchain-openai`. NVIDIA API Catalog
(`build.nvidia.com`, via `langchain-nvidia-ai-endpoints`) is still available
through `utils/llm.py`, but its inference backend proved too unreliable
(frequent read timeouts / unresponsive requests, even on trivial calls) to
use as the default -- see "Known limitations" below.

## Setup

```bash
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENROUTER_API_KEY at minimum
```

## Structure

```
config/                     Configuration (LLM base_url, data paths, scenario thresholds)
data/infra/                 Available infrastructure (nodes, links) — nodes.csv (cpu_cores,
                              ram_gb, storage_gb, optional mips for execution-time calculation),
                              links.csv (bandwidth_mbps, propagation_delay_ms)
data/app_state/              Current application state: services.json (services T1-T5, their
                              placement, static resource footprint, optional workload_mi/
                              output_size) + flows.json (named, ordered chains of services,
                              e.g. the end-to-end video pipeline)
src/agent/
  graph.py                    StateGraph assembly (nodes + conditional routing)
  model/schemas.py             Domain schemas (Node, Link, Service, Flow, Application,
                                ExtractedRequirement, Requirement, NecessityCheckResult,
                                DecisionResult)
  states/state.py              AgentState (shared graph state)
  nodes/
    intent_grounding.py          LLM node: requirement extraction, then validation and
                                  normalization (utils/requirement_validation.py)
    necessity_checker.py         Structured node: is reconfiguration needed or not --
                                  reuses utils/pipeline.py's capacity_satisfied/
                                  latency_satisfied, restricted to the nodes/flows the
                                  active requirements could possibly affect
    decision_engine.py           Homemade brute-force CSP solver (see
                                  utils/csp_solver.py) -- an alternative backend, not
                                  wired into the graph; used directly by the
                                  already-recorded public_safety campaign
    decision_engine_cp_sat.py    Same problem solved with CP-SAT (Google OR-Tools) --
                                  the one wired into the graph (see
                                  utils/csp_constraints_cp_sat.py)
    explanation.py               LLM node: explanation generation
  prompts/                     System prompts used by the LLM nodes
  utils/
    config.py                     Loading config.yaml + .env
    data_loader.py                 Loading nodes/links/services/flows
    llm.py                         NVIDIA chat model retrieval (ChatNVIDIA) -- available,
                                    not the default (see "Known limitations")
    llm_openrouter.py               OpenRouter chat model retrieval (ChatOpenAI) -- default
    requirement_validation.py       validate_and_normalize: checks each extracted
                                     requirement's kpi/target-type/comparator shape,
                                     grounds its target_id against the application state,
                                     checks source_span is a literal substring of the
                                     intent, and converts its value to the KPI's
                                     canonical unit -- a failing requirement carries a
                                     reason, never silently dropped
    pipeline.py                     Shared helpers. service_processing_delay_ms (a
                                     service's own execution time -- workload_mi/
                                     node.mips if both declared, else wcet_ms, else 0)
                                     and shortest_path_delays_ms (Dijkstra over the
                                     links graph: transmission + propagation per hop,
                                     multi-hop, not just a direct link) feed
                                     flow_latency_ms. effective_service_capacity/
                                     effective_flow_latency_target resolve whether a
                                     service/flow uses its static baseline
                                     (Service.requirements/Flow.requirements) or the
                                     current intent's override; capacity_satisfied/
                                     latency_satisfied check those as permanent
                                     invariants, optionally restricted to a subset of
                                     nodes/flows (see necessity_checker.py).
                                     to_native_unit converts an extracted value to its
                                     KPI's canonical unit.
    csp_checks.py                   check_connectivity -- direct-link-only
                                     connectivity, kept only because
                                     expérimentations/public_safety/baseline/verifier.py
                                     still depends on its original semantics; the real
                                     pipeline no longer uses it (multi-hop routing via
                                     pipeline.py:shortest_path_delays_ms instead)
    csp_solver.py                   Homemade solver: brute-force search (solve_placement),
                                     per-service diagnostic (diagnose_node_options),
                                     trace formatting (format_diagnosis)
    csp_constraints_cp_sat.py       CP-SAT constraint builders, one per verification --
                                     used only by decision_engine_cp_sat.py
scripts/run_scenario.py     Entry point: replays the running example from the slides
tests/                        Tests for the structured nodes (requirement validation,
                               necessity checker, both decision engine backends) and
                               the explanation prompt
testbench.ipynb              Notebook for manually exercising individual nodes/components
```

## Graph

```
Intent Grounding -> Necessity Checker --reconfiguration_required--> Decision Engine -\
                                       \--reconfiguration_not_required----------------> Explanation -> END
```

## Decision Engine: two interchangeable solvers

Service placement is modeled as a Constraint Satisfaction / Optimization
Problem: every service is a variable (which node hosts it), constrained by
cpu/ram capacity and cumulative end-to-end latency -- computed over the
minimum-delay path between two services' nodes, not just a direct link --
with an objective that prefers leaving services where they are (only moving
what's strictly necessary), then the cheapest infrastructure tier.

Two implementations of that same model exist, producing the identical
`DecisionResult` shape:
- **`decision_engine_cp_sat.py` / `utils/csp_constraints_cp_sat.py`**: the
  same problem solved with CP-SAT (Google OR-Tools), a genuine
  constraint-propagation solver. This is the one `graph.py` currently wires
  into the pipeline. Only ever accepts a proven-`OPTIMAL` solution -- an
  unproven `FEASIBLE`, `UNKNOWN`, or `MODEL_INVALID` status raises rather
  than silently returning an unoptimal placement (no search limit is
  configured today, so in practice only `OPTIMAL`/`INFEASIBLE` are ever
  reached).
- **`decision_engine.py` / `utils/csp_solver.py`**: a homemade,
  dependency-free brute-force search -- enumerates every
  `len(nodes) ** len(services)` candidate placement and keeps the best valid
  one. Not called by `graph.py` anymore; kept as an alternative backend and
  used directly (bypassing the graph) by the already-recorded
  `public_safety` campaign.

Both produce a `resolution_trace` (why the chosen placement is valid, and
why each moved service had to move -- `utils/pipeline.py:
check_candidate_placement`/`explain_moved_services`, shared by both
backends so the explanation is identical regardless of which one ran) and a
`search_trace` (how the search got there). `utils/csp_solver.py:
diagnose_node_options` additionally answers "why not node X for this one
service?" independently of a full solve.

## Run the running example

```bash
python scripts/run_scenario.py
```

## Tests

```bash
pytest
```

## Known limitations / TODO

- **NVIDIA API Catalog unreliable**: `utils/llm.py`'s models (`get_mistral_llm`,
  `get_openai_llm`, `get_meta_llm`, `get_nvidia_llm`) hit frequent read
  timeouts and unresponsive requests during development, confirmed via raw
  `curl` to independently rule out our own code/network. `intent_grounding.py`
  and `explanation.py` use `utils/llm_openrouter.py` instead as a result.
- **Every service and every flow has a permanent baseline requirement**
  (`Service.requirements` for cpu/ram, `Flow.requirements["latency"]`),
  checked as a permanent invariant via `utils/pipeline.py:capacity_satisfied`/
  `latency_satisfied`. The current intent's `Requirement` *replaces* the
  baseline for the exact `(target_type, target_id, kpi_type)` it names;
  every other service/flow keeps its baseline. A service/flow without a
  declared baseline contributes `0`/is skipped, never an error.
  `necessity_checker.py` restricts these checks to only the nodes/flows an
  active requirement could possibly affect (the node hosting a targeted
  service -- summed over everyone co-located there, including untouched
  services' baselines; a targeted flow, or a flow containing a targeted
  service), on the assumption the real, already-deployed placement already
  satisfies every baseline elsewhere.
- `latency` requirements always target a `Flow` (`target_type="flow"`),
  never a single service, and are evaluated as the sum of each service's
  own execution time (`workload_mi / node.mips` if both are declared, else
  `wcet_ms` if declared, else `0` -- `pipeline.py:service_processing_delay_ms`)
  plus per-hop communication delay. Communication delay is transmission
  (`ceil(output_size / link.bandwidth_mbps)`, `0` if `output_size` isn't
  declared) plus propagation (`link.propagation_delay_ms`), summed along the
  *minimum-delay path* between the two services' nodes -- a Dijkstra search
  over the links graph (`pipeline.py:shortest_path_delays_ms`), not just a
  direct link. Consecutive services no longer need to be co-located or
  directly linked; the only remaining failure is two nodes with no path
  between them at all (a genuinely disconnected infrastructure graph).
  Several flows may freely share services at their endpoints (no merge-point
  restriction: that was a limitation of the previous `Service.next_services`
  model, resolved by moving topology to `Flow.path`).
- `decision_engine.py`/`decision_engine_cp_sat.py` never raise when no
  placement satisfies every constraint -- `DecisionResult.outcome` is
  `"FEASIBLE"` or `"INFEASIBLE"` (`csp_solver.py:solve_placement` returns
  `None` instead of raising), and `explanation_node` has an explicit case for
  `INFEASIBLE` (placement left unchanged, never described as a successful
  reconfiguration).
- `decision_engine.py`'s brute-force solver is `O(len(nodes) ** len(services))`
  -- fine for the running example (5 services, 6-7 nodes), would need to
  switch to `decision_engine_cp_sat.py` (or a smarter search) if the
  infrastructure/pipeline grows substantially.
- `intent_grounding.py`: assumes the LLM returns the exact `target_id`
  (a `service_id` or `flow_id` from the provided lists), no approximate
  matching on natural-language names.
- Only `cpu`, `ram`, and `latency` are supported KPIs -- `bandwidth`,
  `packet_loss`, and `reliability` (link-level KPIs) are deferred: unlike
  `latency`, which resolves to network hops via `Flow.path`, these would
  need the same kind of service-to-link mapping applied per intent, not yet
  designed. Each KPI accepts several unit spellings (e.g. `core`,
  `millicore`, `MiB`, `seconds`) matching the intent's own phrasing --
  `utils/requirement_validation.py` normalizes to each KPI's canonical unit
  (`vCPU`, `GB`, `ms`) and rejects an unrecognized `(kpi_type, unit)` pairing
  rather than guessing.
