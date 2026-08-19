# Intent-Based Service Offloading in the Cloud Continuum

Implementation of the pipeline described in the slides (Intent Grounding →
Offloading Decision → Trace & Explanation Generation) as a **LangGraph**
graph, on the "real-time video analysis" running example (scenario 1).
The models used are NVIDIA models (API Catalog, build.nvidia.com) via the
official `langchain-nvidia-ai-endpoints` integration.

## Setup

```bash
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in NVIDIA_API_KEY and LLM_MODEL
```

## Structure

```
config/                  Configuration (LLM base_url, data paths, scenario thresholds)
data/infra/                 Available infrastructure (nodes, links) — nodes.csv, links.csv
data/app_state/             Current application state (services T1-T5 and their placement)
src/agent/
  graph.py                    StateGraph assembly (nodes + conditional routing)
  model/schemas.py             Domain schemas (Node, Link, Service, Requirement,
                                NecessityCheckResult, DecisionResult)
  states/state.py              AgentState (shared graph state)
  nodes/
    intent_grounding.py          LLM node: requirement extraction + matching
    necessity_checker.py         Structured node: is reconfiguration needed or not
    decision_engine.py           Solver node: new placement (v0 greedy)
    explanation.py               LLM node: explanation generation
  prompts/                     System prompts used by the LLM nodes
  utils/
    config.py                     Loading config.yaml + .env
    data_loader.py                 Loading nodes/links/services
    llm.py                         NVIDIA chat model retrieval (ChatNVIDIA)
scripts/run_scenario.py     Entry point: replays the running example from the slides
tests/                        Tests for the structured nodes (necessity checker, decision engine)
```

## Graph

```
Intent Grounding -> Necessity Checker --reconfiguration_required--> Decision Engine -\
                                       \--no_action_needed---------------------------> Explanation -> END
```

## Run the running example

```bash
python scripts/run_scenario.py
```

## Tests

```bash
pytest
```

## Known limitations / TODO

- `decision_engine.py`: greedy solver (lowest tier satisfying the
  constraints), does not yet account for multi-service end-to-end latency or
  network links — to be replaced with a proper constraint solver.
- `intent_grounding.py`: assumes the LLM returns the exact `service_id`, no
  approximate matching on natural-language service names.
- Node `N6`, referenced in the links (L6, L7, L9) from the slides, does not
  appear in the nodes table — an inconsistency present in the original
  material, to be clarified before using network links in the solver.
- No evaluation benchmark yet for the extraction step (cf. the "Evaluation"
  slide) — to be built.
