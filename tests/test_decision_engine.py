from agent.model.schemas import NecessityCheckResult, Node, Requirement, Service
from agent.nodes.decision_engine import decision_engine_node


def _nodes() -> dict[str, Node]:
    return {
        "N5": Node(
            node_id="N5", node_name="IntelNUC_Fog", tier="fog", node_type="fog_node",
            cpu_cores=8, ram_gb=16, storage_gb=512,
        ),
        "N7": Node(
            node_id="N7", node_name="Cloud_A100", tier="cloud", node_type="cloud_gpu_node",
            cpu_cores=96, ram_gb=900, storage_gb=10000,
        ),
    }


def test_migrates_to_cloud_when_fog_insufficient():
    state = {
        "necessity_result": NecessityCheckResult(
            status="reconfiguration_required",
            violated_constraints=["req-001", "req-002"],
        ),
        "requirements": [
            Requirement(
                requirement_id="req-001", kpi_type="cpu", comparator="gte", target_value=12,
                unit="vCPU", target_type="service", target_id="T3", source_span="12 vCPU",
            ),
            Requirement(
                requirement_id="req-002", kpi_type="ram", comparator="gte", target_value=24,
                unit="GB", target_type="service", target_id="T3", source_span="24GB of RAM",
            ),
        ],
        "services": {
            "T3": Service(
                service_id="T3", name="Detection", description="Object detection", current_node="N5",
            ),
        },
        "flows": {},
        "nodes": _nodes(),
        "links": [],
    }

    result = decision_engine_node(state)["decision_result"]

    assert result.decision == {"T3": "N7"}
    assert result.new_configuration["T3"] == "N7"
    assert set(result.requirements_satisfied) == {"req-001", "req-002"}


def test_relocates_when_co_located_footprint_leaves_no_room():
    # T3 and T4 both start on N5 (8 cores). T4 declares a 7-vCPU footprint,
    # leaving only 1 vCPU actually free -- not enough for T3's 3-vCPU floor.
    # Either T3 or T4 may be the one that ends up moving (both are valid,
    # equally-cheap resolutions), so the test only asserts the invariant
    # that must hold either way: they can't both still be on N5.
    t4 = Service(
        service_id="T4", name="Tracking", description="Multi-frame object tracking",
        current_node="N5", requirements={"cpu_cores": 7},
    )
    t3 = Service(service_id="T3", name="Detection", description="Object detection", current_node="N5")

    state = {
        "necessity_result": NecessityCheckResult(
            status="reconfiguration_required",
            violated_constraints=["req-001"],
        ),
        "requirements": [
            Requirement(
                requirement_id="req-001", kpi_type="cpu", comparator="gte", target_value=3,
                unit="vCPU", target_type="service", target_id="T3", source_span="3 vCPU",
            ),
        ],
        "services": {"T3": t3, "T4": t4},
        "flows": {},
        "nodes": _nodes(),
        "links": [],
    }

    result = decision_engine_node(state)["decision_result"]

    assert len(result.decision) >= 1
    assert not (result.new_configuration["T3"] == "N5" and result.new_configuration["T4"] == "N5")
