from agent.model.schemas import Node, Requirement, Service
from agent.nodes.decision_engine_cp_sat import decision_engine_node_cp_sat


def _nodes() -> dict[str, Node]:
    return {
        "N5": Node(
            node_id="N5", node_name="IntelNUC_Fog", tier="fog", node_type="fog_node",
            cpu_cores=8, cpu_freq_ghz=3.6, ram_gb=16, storage_gb=512, mobility="static",
        ),
        "N7": Node(
            node_id="N7", node_name="Cloud_A100", tier="cloud", node_type="cloud_gpu_node",
            cpu_cores=96, cpu_freq_ghz=2.5, ram_gb=900, storage_gb=10000, mobility="static",
        ),
    }


def test_migrates_to_cloud_when_fog_insufficient():
    state = {
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

    result = decision_engine_node_cp_sat(state)["decision_result"]

    assert result.decision == {"T3": "N7"}
    assert result.new_configuration["T3"] == "N7"


def test_capacity_constraint_accounts_for_co_located_footprint():
    # T3 and T4 both start on N5 (8 cores). T4 declares a 7-vCPU footprint,
    # leaving only 1 vCPU actually free -- not enough for T3's 3-vCPU floor.
    # Either T3 or T4 may be the one the solver relocates (both are valid,
    # equally-cheap resolutions -- see csp_constraints_cp_sat.py), so the
    # test only asserts the invariant that must hold either way: they can't
    # both still be on N5 once solved, since that combination is infeasible.
    t4 = Service(
        service_id="T4", name="Tracking", description="Multi-frame object tracking",
        current_node="N5", requirements={"cpu_cores": 7},
    )
    t3 = Service(service_id="T3", name="Detection", description="Object detection", current_node="N5")

    state = {
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

    result = decision_engine_node_cp_sat(state)["decision_result"]

    assert len(result.decision) >= 1
    assert not (result.new_configuration["T3"] == "N5" and result.new_configuration["T4"] == "N5")
