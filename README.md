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
data/app_state/              Current application state (services T1-T5, their placement,
                              and the pipeline DAG via next_services)
src/agent/
  graph.py                    StateGraph assembly (nodes + conditional routing)
  model/schemas.py             Domain schemas (Node, Link, Service, Requirement,
                                NecessityCheckResult, DecisionResult)
  states/state.py              AgentState (shared graph state)
  nodes/
    intent_grounding.py          LLM node: requirement extraction + matching
    necessity_checker.py         Structured node: is reconfiguration needed or not
                                  (cpu/ram capacity + cumulative pipeline latency)
    decision_engine.py           Homemade brute-force CSP solver -- the one wired
                                  into the graph (see utils/csp_solver.py)
    decision_engine_cp_sat.py    Same problem solved with CP-SAT (Google OR-Tools) --
                                  kept as a reference, not used by the graph
    explanation.py               LLM node: explanation generation
  prompts/                     System prompts used by the LLM nodes
  utils/
    config.py                     Loading config.yaml + .env
    data_loader.py                 Loading nodes/links/services
    llm.py                         NVIDIA chat model retrieval (ChatNVIDIA) -- available,
                                    not the default (see "Known limitations")
    llm_openrouter.py               OpenRouter chat model retrieval (ChatOpenAI) -- default
    pipeline.py                     Pipeline DAG helpers (next_services traversal,
                                     cumulative latency, link lookup) shared by
                                     necessity_checker and the CSP solvers
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

## Enact scenario & intent datasets

`data/enact_scenario/` is a second, additive scenario (real weather-forecasting telemetry from
`dataset/enact/`, extended with generic nodes across every continuum tier) -- built without
touching `data/infra/`, `data/app_state/`, or the pre-existing `data/eval/` fixtures. Full
write-up (topology, services, telemetry, every intent, every pipeline run) in
[`data/enact_scenario/RESULTS.md`](data/enact_scenario/RESULTS.md); the generation method behind
every file and every intent (sources, formulas, what's hand-authored vs. LLM-generated) is in
[`data/enact_scenario/METHODOLOGY.md`](data/enact_scenario/METHODOLOGY.md).

Intent datasets, in `data/eval/`:
- `intent_grounding_enact.jsonl` -- pre-existing, 10 hand-picked ground-truth cases (RAM only),
  grounded on `dataset/enact/pod_telemetry_pods_on.csv` measurements.
- `intent_grounding_enact_variants.jsonl` -- pre-existing, 30 paraphrases of the above,
  **LLM-generated** by `scripts/generate_intent_dataset.py` (`prompts/intent_generation.py`
  asks the LLM to reword a known ground-truth requirement into one natural sentence, anti-
  canonical phrasing enforced by the prompt).
- `intent_grounding_enact_extended.jsonl` -- 14 new cases (cpu/energy/latency KPIs, plus 3
  offload-trigger scenarios on `C1`/`C2-v2`/`F2-v2`). **Hand-authored, not LLM-generated**:
  each floor/ceiling value comes directly from computed mean/p95/max statistics on real
  `pod_telemetry_pods_on.csv` readings (or from `cumulative_latency_ms` on the new
  `services_pipeline.json` DAG for the latency cases), picked by hand to be deliberately
  satisfied or violated.
- `intent_grounding_enact_clarity_spectrum.jsonl` -- 20 new cases spanning 5 clarity tiers
  (explicit -> casual -> implicit -> noisy -> vague-with-no-threshold), grounded on
  `dataset/enact/node_telemetry_pods_on.csv` node-level stats (cpu/energy/storage/network
  in-out). **Also hand-authored, not LLM-generated** -- unlike the `_variants.jsonl` file
  above, no LLM was used to produce the intent text itself; the point of this file is instead
  to *measure* the LLM's extraction (`intent_grounding_node`) as clarity degrades. Results of
  running it 3x per case through the real pipeline: `data/enact_scenario/RESULTS.md`, Part 3.

Formal evaluation harness (extraction accuracy + decision-layer correctness, scored separately,
raw/scored data persisted, analysis notebook with tables and figures): `experimentation/`.
Methodology (two-layer principle, metric definitions, error taxonomies, known limitations) in
[`experimentation/METHODOLOGY.md`](experimentation/METHODOLOGY.md); report-ready result tables
in [`experimentation/RESULTS.md`](experimentation/RESULTS.md).

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
- `necessity_checker.py`: `latency` requirements are evaluated as cumulative
  network latency from the pipeline's root down to the service (via each
  service's `next_services` edges and `data/infra/links.csv`), not a
  per-service processing/compute time. This assumes (a) the pipeline DAG has
  no merge points (a service with more than one predecessor raises an
  error), and (b) every pair of consecutive services is hosted on the same
  node or on two directly linked nodes — multi-hop routing between
  non-adjacent nodes is not supported (an error for necessity_checker's real
  placement, an invalid candidate for the CSP solvers evaluating hypothetical
  ones).
- `decision_engine.py`'s brute-force solver is `O(len(nodes) ** len(services))`
  -- fine for the running example (5 services, 6-7 nodes), would need to
  switch to `decision_engine_cp_sat.py` (or a smarter search) if the
  infrastructure/pipeline grows substantially.
- `intent_grounding.py`: assumes the LLM returns the exact `service_id`, no
  approximate matching on natural-language service names.
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
