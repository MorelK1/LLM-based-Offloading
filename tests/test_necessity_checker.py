from agent.model.schemas import Node, Requirement, Service
from agent.nodes.necessity_checker import necessity_checker_node


def _fog_node() -> Node:
    return Node(
        node_id="N5",
        node_name="IntelNUC_Fog",
        tier="fog",
        node_type="fog_node",
        cpu_cores=8,
        cpu_freq_ghz=3.6,
        ram_gb=16,
        storage_gb=512,
        mobility="static",
    )


def _detection_service() -> Service:
    return Service(
        service_id="T3",
        name="Detection",
        description="Object detection",
        current_node="N5",
    )


def test_reconfiguration_required_when_node_undersized():
    state = {
        "requirements": [
            Requirement(
                requirement_id="req-001",
                kpi_type="cpu",
                comparator="gte",
                target_value=12,
                unit="vCPU",
                service="T3",
                source_span="12 vCPU",
            ),
        ],
        "services": {"T3": _detection_service()},
        "nodes": {"N5": _fog_node()},
    }

    result = necessity_checker_node(state)["necessity_result"]

    assert result.status == "reconfiguration_required"
    assert result.violated_requirements == ["req-001"]
    assert result.services_to_reconsider == ["T3"]


def test_no_action_needed_when_requirements_satisfied():
    state = {
        "requirements": [
            Requirement(
                requirement_id="req-001",
                kpi_type="cpu",
                comparator="gte",
                target_value=4,
                unit="vCPU",
                service="T3",
                source_span="4 vCPU",
            ),
        ],
        "services": {"T3": _detection_service()},
        "nodes": {"N5": _fog_node()},
    }

    result = necessity_checker_node(state)["necessity_result"]

    assert result.status == "no_action_needed"
    assert result.violated_requirements == []
