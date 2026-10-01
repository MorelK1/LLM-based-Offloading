from agent.model.schemas import DecisionResult, NecessityCheckResult, Node, Service
from agent.prompts.explanation import _translate_ids, build_user_prompt


def _node(node_id: str, tier: str) -> Node:
    return Node(
        node_id=node_id,
        node_name=node_id,
        tier=tier,
        node_type=f"{tier}_node",
        cpu_cores=8,
        cpu_freq_ghz=2.0,
        ram_gb=16,
        storage_gb=100,
        mobility="static",
    )


def _service(service_id: str, name: str, current_node: str) -> Service:
    return Service(service_id=service_id, name=name, description="", current_node=current_node)


def test_translate_ids_replaces_each_id_with_its_own_service_name():
    services = {
        "T1": _service("T1", "Alpha", "N1"),
        "T10": _service("T10", "Beta", "N1"),
    }
    text = "T1 and T10 are both on N1"

    result = _translate_ids(text, services, {}, {})

    assert result == "the Alpha service and the Beta service are both on N1"


def test_translate_ids_qualifies_nodes_with_tier():
    nodes = {"N5": _node("N5", "fog")}

    result = _translate_ids("service moved to N5", {}, nodes, {})

    assert result == "service moved to the fog node N5"


def test_forced_move_reason_is_separated_from_other_checks():
    # Mirrors the real wording from csp_solver.py's _explain_moved_services:
    # a forced move always reads "<service> could not stay on <node>: <reason>".
    decision = DecisionResult(
        outcome="FEASIBLE",
        decision={"T2": "N5"},
        eligible_nodes_considered=["N5", "N7"],
        requirements_satisfied=["req-001"],
        new_configuration={"T2": "N5", "T3": "N7"},
        resolution_trace=[
            "cpu_cores on N7: 12.0 of 96 used by ['T3'] ok",
            "T2 could not stay on N1: no direct link between N1 and N7",
        ],
        search_trace=["explored 10 candidates"],
    )

    prompt = build_user_prompt(
        "intent text",
        [],
        necessity_result=NecessityCheckResult(
            status="reconfiguration_required", violated_requirements=["req-001"], services_to_reconsider=["T2"]
        ),
        decision_result=decision,
        services={"T2": _service("T2", "Preprocessing", "N1"), "T3": _service("T3", "Detection", "N7")},
        nodes={"N1": _node("N1", "iot"), "N5": _node("N5", "fog"), "N7": _node("N7", "cloud")},
        flows={},
    )

    why_section = prompt.split("Why each moved service moved")[1].split("Other checks")[0]
    other_section = prompt.split("Other checks confirming the new placement is valid:")[1]

    assert "could not stay on" in why_section
    assert "Preprocessing" in why_section
    # The unrelated capacity-ok line must NOT leak into the move-reasons
    # section -- that's exactly the ambiguity that caused the model to
    # misattribute forced-vs-optional in practice.
    assert "cpu_cores on" not in why_section
    assert "cpu_cores on" in other_section


def test_optional_move_reason_is_labeled_distinctly_from_forced():
    decision = DecisionResult(
        outcome="FEASIBLE",
        decision={"T2": "N5"},
        eligible_nodes_considered=["N5"],
        requirements_satisfied=["req-001"],
        new_configuration={"T2": "N5"},
        resolution_trace=[
            "T2 did not strictly need to move off N1 (staying would still satisfy every "
            "constraint) -- it moved only because the search found a cheaper overall configuration",
        ],
        search_trace=[],
    )

    prompt = build_user_prompt(
        "intent text",
        [],
        necessity_result=NecessityCheckResult(
            status="reconfiguration_required", violated_requirements=["req-001"], services_to_reconsider=["T2"]
        ),
        decision_result=decision,
        services={"T2": _service("T2", "Preprocessing", "N1")},
        nodes={"N1": _node("N1", "iot"), "N5": _node("N5", "fog")},
        flows={},
    )

    why_section = prompt.split("Why each moved service moved")[1].split("Other checks")[0]
    assert "did not strictly need to move off" in why_section
