"""LangGraph node: Decision Engine (CSP solver, structured module).

CP-SAT (Google OR-Tools) implementation, kept as a reference/alternative
alongside the homemade brute-force solver in decision_engine.py, which is
the one currently wired into the graph. Not used by the graph for now.

Models service placement as a Constraint Satisfaction / Optimization Problem:
every service is a variable (which node hosts it). The hard constraints
themselves (cpu, ram, connectivity, latency) live in
utils/csp_constraints_cp_sat.py, one function per verification -- this node
only builds the assignment variables, applies each constraint family, sets
the objective, solves, and turns the solution back into a DecisionResult.

The objective strongly prefers leaving each service on its current node --
the solver only moves a service when a constraint actually forces it to,
among possibly several services at once if that's what satisfying every
constraint jointly requires.
"""

from ortools.sat.python import cp_model

from agent.model.schemas import DecisionResult
from agent.states.state import AgentState
from agent.utils.csp_constraints_cp_sat import (
    add_connectivity_constraints_cp_sat,
    add_cpu_constraints_cp_sat,
    add_latency_constraints_cp_sat,
    add_ram_constraints_cp_sat,
)

_TIER_ORDER = {"iot": 0, "edge": 1, "fog": 2, "cloud": 3}
_KPI_TYPES_MODELED = ("cpu", "ram", "latency")
# Weight of "this service moved from its current node" in the objective --
# large enough to always dominate the tier-cost tie-breaker below, so the
# solver never relocates a service unless a constraint forces it to.
_STABILITY_WEIGHT = 1000


def decision_engine_node_cp_sat(state: AgentState) -> dict:
    services = state["services"]
    nodes = state["nodes"]
    links = state["links"]
    requirements = state["requirements"]

    service_ids = list(services.keys())
    node_ids = list(nodes.keys())

    model = cp_model.CpModel()

    # x[s][n] == 1 iff service s is placed on node n.
    x = {s: {n: model.NewBoolVar(f"x_{s}_{n}") for n in node_ids} for s in service_ids}
    for s in service_ids:
        model.Add(sum(x[s][n] for n in node_ids) == 1)

    add_cpu_constraints_cp_sat(model, x, requirements, nodes)
    add_ram_constraints_cp_sat(model, x, requirements, nodes)
    add_connectivity_constraints_cp_sat(model, x, services, links, node_ids)
    add_latency_constraints_cp_sat(model, x, services, links, requirements, node_ids)

    # --- objective: minimize disruption first, infrastructure cost second ---
    disruption = sum(
        _STABILITY_WEIGHT * (1 - x[s][services[s].current_node]) for s in service_ids
    )
    infra_cost = sum(
        _TIER_ORDER[nodes[n].tier] * x[s][n] for s in service_ids for n in node_ids
    )
    model.Minimize(disruption + infra_cost)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError(
            "No placement satisfies the cpu/ram/connectivity/latency constraints."
        )

    new_configuration: dict[str, str] = {}
    decision: dict[str, str] = {}
    for s in service_ids:
        chosen = next(n for n in node_ids if solver.Value(x[s][n]))
        new_configuration[s] = chosen
        if chosen != services[s].current_node:
            decision[s] = chosen

    # Correct by construction: every requirement here was modeled as a hard
    # constraint above, so it necessarily holds in any solution the solver
    # returns. A KPI with no constraint modeled (future extension) is simply
    # never included here, rather than being falsely claimed as satisfied.
    requirements_satisfied = [
        r.requirement_id for r in requirements if r.kpi_type in _KPI_TYPES_MODELED
    ]

    decision_result = DecisionResult(
        decision=decision,
        eligible_nodes_considered=sorted(node_ids),
        requirements_satisfied=requirements_satisfied,
        new_configuration=new_configuration,
    )
    return {"decision_result": decision_result}
