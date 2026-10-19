"""LangGraph node: Necessity Checker (structured module, no LLM).

Decides whether the current, real placement already satisfies every active
requirement of the current intent, by reusing the exact same invariant
checks the solvers use (capacity_satisfied/latency_satisfied) -- restricted
to the subset of nodes/flows the active requirements could possibly affect,
rather than the whole infrastructure. This guarantees this module can never
disagree with the solvers about what "satisfied" means (an earlier,
separate per-requirement implementation could: two requirements checked in
isolation could each look satisfiable against the OTHER's stale baseline,
while demanding both at once would overflow a shared node -- see
pipeline.py:capacity_satisfied's own note on this).
"""

from agent.model.schemas import NecessityCheckResult
from agent.states.state import AgentState
from agent.utils.pipeline import capacity_satisfied, latency_satisfied


def necessity_checker_node(state: AgentState) -> dict:
    services = state["services"]
    flows = state["flows"]
    requirements = state["requirements"]
    current_placement = {sid: s.current_node for sid, s in services.items()}

    # Scope: only nodes/flows an active requirement could possibly affect --
    # the real placement is assumed to already satisfy every baseline
    # elsewhere (see module docstring), so nothing outside this scope can
    # have newly broken.
    relevant_nodes: set[str] = set()
    relevant_flows: set[str] = set()
    for req in requirements:
        if req.target_type == "service" and req.kpi_type in ("cpu", "ram"):
            service = services.get(req.target_id)
            if service is None:
                continue
            relevant_nodes.add(service.current_node)
            # Not relevant to latency under the current execution-time model
            # (workload/mips, independent of cpu_cores) -- scoped anyway so
            # a future cpu-affects-latency coupling doesn't need this
            # restriction touched again, only the model itself.
            relevant_flows.update(
                flow_id for flow_id, flow in flows.items() if req.target_id in flow.path
            )
        elif req.target_type == "flow" and req.kpi_type == "latency":
            if req.target_id in flows:
                relevant_flows.add(req.target_id)

    checks = capacity_satisfied(state["nodes"], services, requirements, current_placement, relevant_nodes)
    checks += latency_satisfied(
        flows, services, state["links"], requirements, current_placement, state["nodes"], relevant_flows
    )

    violated = [reason for ok, reason in checks if not ok]
    status = "reconfiguration_required" if violated else "reconfiguration_not_required"
    necessity_result = NecessityCheckResult(
        status=status,
        violated_constraints=violated,
        current_placement=current_placement,
    )
    return {"necessity_result": necessity_result}
