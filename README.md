# Intent-Based Service Offloading in the Cloud Continuum

Implementation of the pipeline described in the slides (Intent Grounding →
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
data/infra/                 Available infrastructure (nodes, links) — nodes.csv, links.csv
data/app_state/              Current application state: services.json (services T1-T5, their
                              placement, static resource footprint) + flows.json (named,
                              ordered chains of services, e.g. the end-to-end video pipeline)
src/agent/
  graph.py                    StateGraph assembly (nodes + conditional routing)
  model/schemas.py             Domain schemas (Node, Link, Service, Flow, Application,
                                Requirement, NecessityCheckResult, DecisionResult)
  states/state.py              AgentState (shared graph state)
  nodes/
    intent_grounding.py          LLM node: requirement extraction + matching
    necessity_checker.py         Structured node: is reconfiguration needed or not --
                                  cpu/ram capacity (per service) + end-to-end latency
                                  (per flow)
    decision_engine.py           Homemade brute-force CSP solver -- the one wired
                                  into the graph (see utils/csp_solver.py)
    decision_engine_cp_sat.py    Same problem solved with CP-SAT (Google OR-Tools) --
                                  kept as a reference, not used by the graph
    explanation.py               LLM node: explanation generation
  prompts/                     System prompts used by the LLM nodes
  utils/
    config.py                     Loading config.yaml + .env
    data_loader.py                 Loading nodes/links/services/flows
    llm.py                         NVIDIA chat model retrieval (ChatNVIDIA) -- available,
                                    not the default (see "Known limitations")
    llm_openrouter.py               OpenRouter chat model retrieval (ChatOpenAI) -- default
    pipeline.py                     Flow helpers (flow_pairs/all_flow_pairs, end-to-end
                                     latency, link lookup, co-located footprint
                                     aggregation) shared by necessity_checker and the
                                     CSP solvers
    csp_checks.py                   Homemade solver: check_cpu/ram/connectivity/latency,
                                     each returning (ok, reason)
    csp_solver.py                   Homemade solver: brute-force search (solve_placement),
                                     per-service diagnostic (diagnose_node_options),
                                     trace formatting (format_diagnosis)
    csp_constraints_cp_sat.py       CP-SAT constraint builders, one per verification --
                                     used only by decision_engine_cp_sat.py
scripts/run_scenario.py     Entry point: replays the running example from the slides
tests/                        Tests for the structured nodes (necessity checker, decision engine)
testbench.ipynb              Notebook for manually exercising individual nodes/components
```

## Graph

```
Intent Grounding -> Necessity Checker --reconfiguration_required--> Decision Engine -\
                                       \--no_action_needed---------------------------> Explanation -> END
```

## Decision Engine: two interchangeable solvers

Service placement is modeled as a Constraint Satisfaction / Optimization
Problem: every service is a variable (which node hosts it), constrained by
cpu/ram capacity, connectivity between consecutive pipeline stages, and
cumulative end-to-end latency, with an objective that prefers leaving
services where they are (only moving what's strictly necessary), then the
cheapest infrastructure tier.

Two implementations of that same model exist:
- **`decision_engine.py` / `utils/csp_solver.py`** (used by the graph): a
  homemade, dependency-free brute-force search -- enumerates every
  `len(nodes) ** len(services)` candidate placement and keeps the best valid
  one. Trivial for the running example's size; does not scale to a much
  larger infrastructure/pipeline.
- **`decision_engine_cp_sat.py` / `utils/csp_constraints_cp_sat.py`**: the
  same problem solved with CP-SAT (Google OR-Tools). Kept as a reference/
  alternative, not wired into the graph.

Both produce a `resolution_trace` (why the chosen placement is valid) and,
for the homemade solver, a `search_trace` (how the search got there).
`utils/csp_solver.py:diagnose_node_options` additionally answers "why not
node X for this one service?" independently of a full solve.

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
- `necessity_checker.py`: `latency` requirements always target a `Flow`
  (`target_type="flow"`), never a single service, and are evaluated as
  cumulative network latency along the whole `Flow.path` (via
  `utils/pipeline.py:flow_latency_ms` and `data/infra/links.csv`), not a
  per-service processing/compute time -- no WCET-style delay is modeled yet.
  Several flows may freely share services at their endpoints (no merge-point
  restriction: that was a limitation of the previous `Service.next_services`
  model, resolved by moving topology to `Flow.path`), but every pair of
  consecutive services *within* a flow must still be hosted on the same node
  or on two directly linked nodes — multi-hop routing between non-adjacent
  nodes is not supported (an error for `necessity_checker`'s real placement,
  an invalid candidate for the CSP solvers evaluating hypothetical ones).
- `cpu`/`ram` requirements with a `lte`/`eq` comparator are compared against
  the service's own declared static footprint (`Service.requirements`), not
  the node's capacity -- but in practice only `gte` is currently produced for
  these two KPIs (see `prompts/requirement_extraction.py`), so this path is
  defensive/untriggered rather than exercised. A service without a declared
  footprint contributes `0` wherever one is expected (co-location aggregation
  for others' `gte` checks, or its own `lte`/`eq` check), never an error.
- `decision_engine.py`'s brute-force solver is `O(len(nodes) ** len(services))`
  -- fine for the running example (5 services, 6-7 nodes), would need to
  switch to `decision_engine_cp_sat.py` (or a smarter search) if the
  infrastructure/pipeline grows substantially.
- `intent_grounding.py`: assumes the LLM returns the exact `target_id`
  (a `service_id` or `flow_id` from the provided lists), no approximate
  matching on natural-language names.
- Only `cpu`, `ram`, and `latency` are supported KPIs -- `bandwidth`,
  `packet_loss`, and `reliability` (link-level KPIs) are deferred: unlike
  `latency`, which resolves to network hops via the pipeline DAG, these would
  need the same kind of service-to-link mapping applied per intent, not yet
  designed.
- Node `N6`, referenced in the links (L6, L7, L9) from the slides, does not
  appear in the nodes table — an inconsistency present in the original
  material. Harmless today (no service ever routes through N6), but would
  need clarifying if the running example's topology is extended.
- No evaluation benchmark yet for the extraction step (cf. the "Evaluation"
  slide) — to be built. `prompts/requirement_extraction.py` already has
  three prompting strategies (`ZERO_SHOT`/`ONE_SHOT`/`FEW_SHOT`) as fully
  hardcoded constants for that future comparison; `ONE_SHOT` has not yet been
  updated with the same multi-requirement lesson as `FEW_SHOT`.
