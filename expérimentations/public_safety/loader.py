"""Loader: maps public_safety's e2e_v2 dataset (data/e2e_v2/*.json) onto our
real schemas (Node, Link, Service, Flow, Requirement) -- field renaming
only, no engine logic duplicated here. necessity_checker_node/
decision_engine_node run UNMODIFIED on the result -- see run_sample.py.
"""

import json
import math
from pathlib import Path

from agent.model.schemas import Flow, Link, Node, Requirement, Service

DATA_DIR = Path(__file__).parent / "data" / "e2e_v2"

# public_safety has no "fog" tier in this dataset, kept for completeness/safety.
_TIER_MAP = {"EDGE": "edge", "IOT": "iot", "FOG": "fog", "CLOUD": "cloud"}


def _read(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


def load_nodes(infrastructure_id: str) -> dict[str, Node]:
    infra = next(
        i for i in _read("infrastructure_nodes.json")["infrastructures"]
        if i["infrastructure_id"] == infrastructure_id
    )
    # Node.cpu_cores/ram_gb are int-typed (Pydantic rejects a fractional
    # float outright) -- floor(), never round(): rounding up could make a
    # node look like it has room it doesn't actually have, silently hiding
    # a real violation at the boundary (confirmed concretely: 8/600 samples
    # mismatched with round(), all of them a raw_available just below an
    # integer target, e.g. 20.59 rounded up to 21 instead of down to 20).
    return {
        n["id"]: Node(
            node_id=n["id"], node_name=n["id"], tier=_TIER_MAP[n["tier"]],
            node_type="generic", cpu_cores=math.floor(n["resources"]["cpu"]),
            cpu_freq_ghz=0.0, ram_gb=math.floor(n["resources"]["ram"]),
            storage_gb=math.floor(n["resources"]["hdd"]), mobility="static",
        )
        for n in infra["nodes"]
    }


def load_links(infrastructure_id: str) -> list[Link]:
    infra = next(
        i for i in _read("infrastructure_links.json")["infrastructures"]
        if i["infrastructure_id"] == infrastructure_id
    )
    # Links are already listed in both directions in the source file --
    # kept as-is (find_link matches on an unordered pair, so duplicates are
    # harmless, just a faithful 1:1 transcription rather than deduplicated).
    return [
        Link(
            link_id=f"L-{link['source']}-{link['target']}", source_node=link["source"],
            target_node=link["target"], link_type="generic",
            bandwidth_mbps=round(link["bandwidth"]), latency_ms=0.0,
            packet_loss_rate=0.0, reliability=1.0,
        )
        for link in infra["links"]
    ]


def load_services_and_flows(
    application_context_id: str,
    current_node_by_id: dict[str, str] | None = None,
) -> tuple[dict[str, Service], dict[str, Flow]]:
    """current_node_by_id overrides each service's current_node -- pass a
    sample's own ground_truth.reconfiguration.initial_placement, since
    different samples sharing the same application_context can start from
    different scenarios/placements. Falls back to the context's own
    "current_node" per service when not given."""
    ctx = next(
        c for c in _read("application_contexts.json")["contexts"]
        if c["application_context_id"] == application_context_id
    )

    services: dict[str, Service] = {}
    for s in ctx["services"]:
        current_node = (current_node_by_id or {}).get(s["id"], s["current_node"])
        output_ports = s.get("output_ports") or []
        services[s["id"]] = Service(
            service_id=s["id"], name=s["name"], description=s.get("description", ""),
            current_node=current_node,
            requirements={
                "cpu_cores": s["requirements"]["cpu"],
                "ram_gb": s["requirements"]["ram"],
                "storage_gb": s["requirements"]["hdd"],
            },
            wcet_ms=s["wcet"][0] if s.get("wcet") else None,
            output_size=output_ports[0]["data_size"] if output_ports else None,
        )

    flows = {
        f["id"]: Flow(
            flow_id=f["id"], name=f["name"], description=f.get("description", ""),
            path=f["path"],
            requirements={"latency": f["current_e2e_max"]} if "current_e2e_max" in f else None,
        )
        for f in ctx["flows"]
    }
    return services, flows


def load_sample(sample_id: str) -> dict:
    samples = _read("e2e_samples.json")["samples"]
    return next(s for s in samples if s["sample_id"] == sample_id)


def requirement_from_sample(sample: dict) -> Requirement:
    sr = sample["ground_truth"]["structured_requirement"]
    return Requirement(
        requirement_id="req-001", kpi_type=sr["kpi_type"], comparator=sr["comparator"],
        target_value=sr["target_value"], unit=sr["unit"],
        target_type=sr["target_type"], target_id=sr["target"],
        source_span=sample["intent"]["text"],
    )
