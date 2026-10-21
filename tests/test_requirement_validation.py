from agent.model.schemas import ExtractedRequirement, Flow, Service
from agent.utils.requirement_validation import validate_and_normalize

INTENT_TEXT = "The detection service needs at least 4 vCPU, and the pipeline must complete within 150ms."


def _services() -> dict[str, Service]:
    return {"T3": Service(service_id="T3", name="Detection", description="", current_node="N5")}


def _flows() -> dict[str, Flow]:
    return {"F1": Flow(flow_id="F1", name="Main pipeline", description="", path=["T1", "T2", "T3"])}


def _cpu_req(**overrides) -> ExtractedRequirement:
    fields = dict(
        kpi_type="cpu", comparator="gte", target_value=4, unit="vCPU",
        target_type="service", target_id="T3", source_span="needs at least 4 vCPU",
    )
    fields.update(overrides)
    return ExtractedRequirement(**fields)


def _latency_req(**overrides) -> ExtractedRequirement:
    fields = dict(
        kpi_type="latency", comparator="lte", target_value=150, unit="ms",
        target_type="flow", target_id="F1", source_span="must complete within 150ms",
    )
    fields.update(overrides)
    return ExtractedRequirement(**fields)


def test_accepts_valid_cpu_requirement():
    requirements, rejected = validate_and_normalize([_cpu_req()], INTENT_TEXT, _services(), _flows())

    assert rejected == []
    assert len(requirements) == 1
    assert requirements[0].requirement_id == "req-001"
    assert requirements[0].target_value == 4
    assert requirements[0].unit == "vCPU"


def test_accepts_valid_latency_requirement():
    requirements, rejected = validate_and_normalize([_latency_req()], INTENT_TEXT, _services(), _flows())

    assert rejected == []
    assert len(requirements) == 1
    assert requirements[0].target_value == 150
    assert requirements[0].unit == "ms"


def test_normalizes_unit_to_canonical():
    req = _cpu_req(target_value=500, unit="millicore", source_span="needs at least 4 vCPU")
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert rejected == []
    assert requirements[0].target_value == 0.5
    assert requirements[0].unit == "vCPU"


def test_rejects_unsupported_kpi():
    # kpi_type isn't a real Literal value here -- model_construct bypasses
    # Pydantic validation on purpose, since no normally-constructed
    # ExtractedRequirement could ever reach this branch today (KpiType's
    # Literal already excludes anything but cpu/ram/latency). This is a
    # forward-compatibility guard, not dead code: it starts mattering the
    # moment KpiType gains a new value EXPECTED_TARGET hasn't caught up to.
    req = ExtractedRequirement.model_construct(
        kpi_type="energy", comparator="gte", target_value=4, unit="vCPU",
        target_type="service", target_id="T3", source_span="needs at least 4 vCPU",
    )
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert requirements == []
    assert len(rejected) == 1
    assert rejected[0].reason == "unsupported_kpi"


def test_rejects_invalid_target_type():
    req = _cpu_req(target_type="flow", target_id="F1")
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert requirements == []
    assert rejected[0].reason == "invalid_target_type"


def test_rejects_unsupported_comparator():
    req = _cpu_req(comparator="lte")
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert requirements == []
    assert rejected[0].reason == "unsupported_comparator"


def test_rejects_unknown_target():
    req = _cpu_req(target_id="T99")
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert requirements == []
    assert rejected[0].reason == "unknown_target"


def test_rejects_invalid_source_span():
    req = _cpu_req(source_span="this text is not in the intent")
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert requirements == []
    assert rejected[0].reason == "invalid_source_span"


def test_rejects_non_positive_value():
    req = _cpu_req(target_value=0)
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert requirements == []
    assert rejected[0].reason == "invalid_value"


def test_rejects_invalid_unit():
    # "ms" is a real Unit literal, just not a valid one for kpi_type="cpu".
    req = _cpu_req(unit="ms")
    requirements, rejected = validate_and_normalize([req], INTENT_TEXT, _services(), _flows())

    assert requirements == []
    assert rejected[0].reason == "invalid_unit"


def test_requirement_ids_assigned_only_to_accepted_and_sequential():
    reqs = [_cpu_req(target_id="T99"), _cpu_req(), _latency_req()]
    requirements, rejected = validate_and_normalize(reqs, INTENT_TEXT, _services(), _flows())

    assert len(rejected) == 1
    assert [r.requirement_id for r in requirements] == ["req-001", "req-002"]
