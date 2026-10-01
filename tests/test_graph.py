from agent.graph import build_graph


def test_include_explanation_true_builds_the_explanation_node():
    graph = build_graph(include_explanation=True)

    assert "explanation" in graph.get_graph().nodes


def test_include_explanation_false_skips_the_explanation_node():
    graph = build_graph(include_explanation=False)

    assert "explanation" not in graph.get_graph().nodes
    assert "intent_grounding" in graph.get_graph().nodes
    assert "necessity_checker" in graph.get_graph().nodes
    assert "decision_engine" in graph.get_graph().nodes
