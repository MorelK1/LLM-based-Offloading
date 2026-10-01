from agent.model.schemas import Flow, Link, Node, Requirement, Service
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
                target_type="service",
                target_id="T3",
                source_span="12 vCPU",
            ),
        ],
        "services": {"T3": _detection_service()},
        "flows": {},
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
                target_type="service",
                target_id="T3",
                source_span="4 vCPU",
            ),
        ],
        "services": {"T3": _detection_service()},
        "flows": {},
        "nodes": {"N5": _fog_node()},
    }

    result = necessity_checker_node(state)["necessity_result"]

    assert result.status == "no_action_needed"
    assert result.violated_requirements == []
    # current_placement lets a consumer read the confirmed-valid placement
    # directly off this result -- decision_engine_node is never called in
    # this branch, so this is the only place it's available from.
    assert result.current_placement == {"T3": "N5"}


def test_current_placement_is_populated_even_when_reconfiguration_is_required():
    # Not just the no_action_needed case -- current_placement always
    # reflects the real placement this check was evaluated against.
    state = {
        "requirements": [
            Requirement(
                requirement_id="req-001",
                kpi_type="cpu",
                comparator="gte",
                target_value=12,
                unit="vCPU",
                target_type="service",
                target_id="T3",
                source_span="12 vCPU",
            ),
        ],
        "services": {"T3": _detection_service()},
        "flows": {},
        "nodes": {"N5": _fog_node()},
    }

    result = necessity_checker_node(state)["necessity_result"]

    assert result.status == "reconfiguration_required"
    assert result.current_placement == {"T3": "N5"}


def test_latency_is_cumulative_across_the_flow():
    # Flow F1: T3 (fog, N5) -> T5 (cloud, N7), linked by L8 (25ms).
    detection = _detection_service()
    storage = Service(
        service_id="T5",
        name="Storage/Big Data Analysis",
        description="Archiving",
        current_node="N7",
    )
    flow = Flow(
        flow_id="F1",
        name="Detection to storage",
        description="T3 -> T5",
        path=["T3", "T5"],
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
                target_type="flow",
                target_id="F1",
                source_span="within 20ms",
            ),
        ],
        "services": {"T3": detection, "T5": storage},
        "flows": {"F1": flow},
        "nodes": {"N5": _fog_node(), "N7": _cloud_node()},
        "links": [link],
    }

    result = necessity_checker_node(state)["necessity_result"]

    # Cumulative latency of the flow (25ms) exceeds the 20ms requirement.
    assert result.status == "reconfiguration_required"
    assert result.violated_requirements == ["req-001"]
    assert result.services_to_reconsider == ["T3", "T5"]


def test_gte_accounts_for_co_located_footprint():
    # T3 and T4 both on N5 (8 cores). T4 declares a 7-vCPU footprint, leaving
    # only 1 vCPU actually available -- not enough for T3's 3-vCPU floor.
    t4 = Service(
        service_id="T4",
        name="Tracking",
        description="Multi-frame object tracking",
        current_node="N5",
        requirements={"cpu_cores": 7},
    )
    state = {
        "requirements": [
            Requirement(
                requirement_id="req-001",
                kpi_type="cpu",
                comparator="gte",
                target_value=3,
                unit="vCPU",
                target_type="service",
                target_id="T3",
                source_span="3 vCPU",
            ),
        ],
        "services": {"T3": _detection_service(), "T4": t4},
        "flows": {},
        "nodes": {"N5": _fog_node()},
    }

    result = necessity_checker_node(state)["necessity_result"]

    assert result.status == "reconfiguration_required"
    assert result.violated_requirements == ["req-001"]


def test_gte_satisfied_once_enough_room_remains_after_co_located_footprint():
    # Same setup, but T4's footprint (3 vCPU) leaves 5 vCPU free on N5 --
    # enough for T3's 3-vCPU floor.
    t4 = Service(
        service_id="T4",
        name="Tracking",
        description="Multi-frame object tracking",
        current_node="N5",
        requirements={"cpu_cores": 3},
    )
    state = {
        "requirements": [
            Requirement(
                requirement_id="req-001",
                kpi_type="cpu",
                comparator="gte",
                target_value=3,
                unit="vCPU",
                target_type="service",
                target_id="T3",
                source_span="3 vCPU",
            ),
        ],
        "services": {"T3": _detection_service(), "T4": t4},
        "flows": {},
        "nodes": {"N5": _fog_node()},
    }

    result = necessity_checker_node(state)["necessity_result"]

    assert result.status == "no_action_needed"


def test_lte_uses_own_footprint_not_node_capacity():
    # N5 has 8 cores -- way above the 10-vCPU ceiling below, so the old
    # buggy comparison (node.cpu_cores <= target, i.e. 8 <= 10) would say
    # "satisfied" without ever looking at what T3 itself actually uses.
    # T3's own declared footprint (12) exceeds its own ceiling (10): that's
    # what should trigger the violation, regardless of the node's capacity.
    t3 = Service(
        service_id="T3",
        name="Detection",
        description="Object detection",
        current_node="N5",
        requirements={"cpu_cores": 12},
    )
    state = {
        "requirements": [
            Requirement(
                requirement_id="req-001",
                kpi_type="cpu",
                comparator="lte",
                target_value=10,
                unit="vCPU",
                target_type="service",
                target_id="T3",
                source_span="at most 10 vCPU",
            ),
        ],
        "services": {"T3": t3},
        "flows": {},
        "nodes": {"N5": _fog_node()},
    }

    result = necessity_checker_node(state)["necessity_result"]

    assert result.status == "reconfiguration_required"
    assert result.violated_requirements == ["req-001"]
