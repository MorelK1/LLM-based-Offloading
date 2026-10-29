"""LangGraph node: Decision Engine (CSP solver, structured module).

CP-SAT (Google OR-Tools) implementation -- the one wired into the graph
(see graph.py). The homemade brute-force solver in decision_engine.py /
utils/csp_solver.py remains available as an alternative backend (and is
what the already-recorded public_safety campaign used).

Models service placement as a Constraint Satisfaction / Optimization Problem:
every service is a variable (which node hosts it). The hard constraints
themselves (cpu, ram, latency) live in utils/csp_constraints_cp_sat.py, one
function per verification -- this node only builds the assignment
variables, applies each constraint family, sets the objective, solves, and
turns the solution back into a DecisionResult. Connectivity is no longer a
modeled requirement in its own right: add_latency_constraints_cp_sat
forbids, inline, a placement across two genuinely disconnected nodes (no
path at all) as part of pricing each hop, rather than as a separate
constraint family.

The objective minimizes disruption alone -- the number of services moved
away from their current node. Ties between equally-disruptive placements
are not broken by anything (no infrastructure-tier preference): which one
CP-SAT returns in that case depends on its own search order.
"""

from ortools.sat.python import cp_model

from agent.model.schemas import DecisionResult
from agent.states.state import AgentState
from agent.utils.csp_constraints_cp_sat import (
    add_capacity_constraints_cp_sat,
    add_fixed_placement_constraints_cp_sat,
    add_latency_constraints_cp_sat,
)
from agent.utils.pipeline import check_candidate_placement, explain_moved_services

_KPI_TYPES_MODELED = ("cpu", "ram", "latency")


def decision_engine_node_cp_sat(state: AgentState) -> dict:
    services = state["services"]
    nodes = state["nodes"]
    links = state["links"]
    requirements = state["requirements"]
    flows = state["flows"]

    service_ids = list(services.keys())
    node_ids = list(nodes.keys())

    model = cp_model.CpModel()

    # x[s][n] == 1 iff service s is placed on node n.
    x = {s: {n: model.NewBoolVar(f"x_{s}_{n}") for n in node_ids} for s in service_ids}
    for s in service_ids:
        model.Add(sum(x[s][n] for n in node_ids) == 1)

    add_capacity_constraints_cp_sat(model, x, nodes, services, requirements)
    add_latency_constraints_cp_sat(model, x, flows, services, links, requirements, node_ids, nodes)
    add_fixed_placement_constraints_cp_sat(model, x, services)

    # --- objective: minimize disruption, the number of services moved ---
    disruption = sum(1 - x[s][services[s].current_node] for s in service_ids)
    model.Minimize(disruption)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        # Proven infeasibility -- no candidate placement satisfies every
        # constraint, surfaced as an explicit INFEASIBLE outcome (see
        # explanation_node) rather than letting the pipeline crash outright.
        decision_result = DecisionResult(
            outcome="INFEASIBLE",
            decision={},
            eligible_nodes_considered=sorted(node_ids),
            requirements_satisfied=[],
            new_configuration={sid: s.current_node for sid, s in services.items()},
            search_trace=[f"CP-SAT solver status: {solver.StatusName(status)}"],
        )
        return {"decision_result": decision_result}
    if status == cp_model.UNKNOWN:
        # Genuinely different from INFEASIBLE: the solver reached no
        # conclusion at all (e.g. a time/work limit was hit first, not
        # modeled today but a real risk once the problem grows). Reporting
        # this as INFEASIBLE would be a false claim of proven infeasibility,
        # so this fails loudly instead of silently mislabeling it.
        raise RuntimeError(
            "CP-SAT returned UNKNOWN: no conclusive result (neither a "
            "solution nor proven infeasibility) -- not the same as INFEASIBLE."
        )
    if status == cp_model.MODEL_INVALID:
        raise RuntimeError(f"Invalid CP-SAT model: {model.Validate()}")
    if status != cp_model.OPTIMAL:
        # FEASIBLE: a valid placement was found, but the solver could not
        # prove it's the best one (e.g. a time/work limit cut the search
        # short before closing the optimality gap -- not configured today,
        # but a real risk once the problem grows). Unlike the brute-force
        # solver, which is exhaustive by construction and therefore always
        # optimal, CP-SAT's FEASIBLE is not an optimality guarantee -- so
        # this fails loudly rather than silently returning an unproven
        # placement as if it were the best one.
        raise RuntimeError(
            f"CP-SAT returned {solver.StatusName(status)}, not OPTIMAL: a "
            "valid placement was found but optimality was not proven."
        )
    # status is OPTIMAL from here on.

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

    # resolution_trace: CP-SAT's model never evaluates a chosen assignment
    # against capacity_satisfied/latency_satisfied the way brute-force's own
    # search does (its constraints are implicit in the model, not checked
    # post hoc) -- so without this, explanation_node would get an empty
    # trace for every CP-SAT-produced decision. Reusing pipeline.py's
    # solver-agnostic helpers against the final new_configuration gives the
    # exact same human-readable trace brute-force produces, including the
    # per-moved-service forced/not-strictly-needed explanation.
    _valid, checks = check_candidate_placement(
        new_configuration, services, nodes, links, requirements, flows
    )
    resolution_trace = [reason for _ok, reason in checks]
    resolution_trace += explain_moved_services(
        new_configuration, services, nodes, links, requirements, flows
    )

    decision_result = DecisionResult(
        outcome="FEASIBLE",
        decision=decision,
        eligible_nodes_considered=sorted(node_ids),
        requirements_satisfied=requirements_satisfied,
        new_configuration=new_configuration,
        resolution_trace=resolution_trace,
        search_trace=[f"CP-SAT solver status: {solver.StatusName(status)}"],
    )
    return {"decision_result": decision_result}
