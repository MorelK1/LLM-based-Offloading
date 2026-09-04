from agent.model.schemas import Link, Node, Requirement, Service
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


def _cloud_node() -> Node:
    return Node(
        node_id="N7",
        node_name="Cloud_A100",
        tier="cloud",
        node_type="cloud_gpu_node",
        cpu_cores=96,
        cpu_freq_ghz=2.5,
        ram_gb=900,
        storage_gb=10000,
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


def test_latency_is_cumulative_across_the_pipeline():
    # T3 (fog, N5) -> T5 (cloud, N7), linked by L8 (25ms).
    detection = _detection_service()
    detection.next_services = ["T5"]
    storage = Service(
        service_id="T5",
        name="Storage/Big Data Analysis",
        description="Archiving",
        current_node="N7",
    )
    link = Link(
        link_id="L8",
        source_node="N5",
        target_node="N7",
        link_type="WAN",
        bandwidth_mbps=10000,
        latency_ms=25.0,
        packet_loss_rate=0.001,
        reliability=0.99,
    )

    state = {
        "requirements": [
            Requirement(
                requirement_id="req-001",
                kpi_type="latency",
                comparator="lte",
                target_value=20,
                unit="ms",
                service="T5",
                source_span="within 20ms",
            ),
        ],
        "services": {"T3": detection, "T5": storage},
        "nodes": {"N5": _fog_node(), "N7": _cloud_node()},
        "links": [link],
    }

    result = necessity_checker_node(state)["necessity_result"]

    # Cumulative latency to T5 (25ms) exceeds the 20ms requirement.
    assert result.status == "reconfiguration_required"
    assert result.violated_requirements == ["req-001"]
    assert result.services_to_reconsider == ["T5"]
