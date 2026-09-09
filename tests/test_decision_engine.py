from agent.model.schemas import NecessityCheckResult, Node, Requirement, Service
from agent.nodes.decision_engine import decision_engine_node


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
        "necessity_result": NecessityCheckResult(
            status="reconfiguration_required",
            violated_requirements=["req-001", "req-002"],
            services_to_reconsider=["T3"],
        ),
        "requirements": [
            Requirement(
                requirement_id="req-001", kpi_type="cpu", comparator="gte", target_value=12,
                unit="vCPU", service="T3", source_span="12 vCPU",
            ),
            Requirement(
                requirement_id="req-002", kpi_type="ram", comparator="gte", target_value=24,
                unit="GB", service="T3", source_span="24GB of RAM",
            ),
        ],
        "services": {
            "T3": Service(
                service_id="T3", name="Detection", description="Object detection", current_node="N5",
            ),
        },
        "nodes": _nodes(),
        "links": [],
    }

    result = decision_engine_node(state)["decision_result"]

    assert result.decision == {"T3": "N7"}
    assert result.new_configuration["T3"] == "N7"
    assert set(result.requirements_satisfied) == {"req-001", "req-002"}
