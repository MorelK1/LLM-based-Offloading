"""LangGraph node: Decision Engine.

Thin wrapper around the homemade brute-force CSP solver in
utils/csp_solver.py: this node only extracts state, calls the solver, and
turns the result into a DecisionResult. See utils/csp_solver.py for the
search itself, and utils/pipeline.py for the individual cpu/ram/latency
verifications (connectivity is no longer a separate check -- multi-hop
routing means only a fully disconnected infrastructure graph is infeasible,
which latency_satisfied already catches).

decision_engine_cp_sat.py / utils/csp_constraints_cp_sat.py is the CP-SAT
(Google OR-Tools) implementation of the same problem, and the one wired
into the graph (see graph.py) -- this brute-force backend remains available
as an alternative, and is what the already-recorded public_safety campaign
used.
"""

from agent.model.schemas import DecisionResult
from agent.states.state import AgentState
from agent.utils.csp_solver import solve_placement

_KPI_TYPES_MODELED = ("cpu", "ram", "latency")


def decision_engine_node(state: AgentState) -> dict:
    services = state["services"]
    requirements = state["requirements"]

    best_candidate, resolution_trace, search_trace = solve_placement(
        services, state["nodes"], state["links"], requirements, state["flows"]
    )

    if best_candidate is None:
        # No candidate placement satisfies every constraint -- surfaced as an
        # explicit INFEASIBLE outcome (see explanation_node) rather than
        # letting the pipeline crash with an unhandled exception.
        decision_result = DecisionResult(
            outcome="INFEASIBLE",
            decision={},
            eligible_nodes_considered=sorted(state["nodes"].keys()),
            requirements_satisfied=[],
            new_configuration={sid: s.current_node for sid, s in services.items()},
            resolution_trace=resolution_trace,
            search_trace=search_trace,
        )
        return {"decision_result": decision_result}

    decision = {
        s: n for s, n in best_candidate.items() if n != services[s].current_node
    }

    # Correct by construction: every requirement here was checked against the
    # actual chosen placement, so it necessarily holds. A KPI with no check
    # implemented (future extension) is simply never included here, rather
    # than being falsely claimed as satisfied.
    requirements_satisfied = [
        r.requirement_id for r in requirements if r.kpi_type in _KPI_TYPES_MODELED
    ]

    decision_result = DecisionResult(
        outcome="FEASIBLE",
        decision=decision,
        eligible_nodes_considered=sorted(state["nodes"].keys()),
        requirements_satisfied=requirements_satisfied,
        new_configuration=best_candidate,
        resolution_trace=resolution_trace,
        search_trace=search_trace,
    )
    return {"decision_result": decision_result}
