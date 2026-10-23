from evals.run import load_cases, score_case
from fieldagent.agent import AgentResult, ToolCall


def test_dataset_is_well_formed():
    cases = load_cases()
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["kind"] for c in cases} == {"docs", "ticket", "abstain"}


def test_score_requires_every_fact_group():
    case = {"id": "x", "kind": "docs", "must_include": [["Data team"], ["Sev 2"]], "expected_sources": ["a.md"]}
    ok = AgentResult(answer="Page the Data team, Sev 2 [a.md]")
    missing = AgentResult(answer="Page the Data team [a.md]")
    assert score_case(case, ok).passed
    assert not score_case(case, missing).passed


def test_score_checks_expected_tools():
    case = {"id": "t", "kind": "ticket", "must_include": [], "expected_tools": ["get_ticket"]}
    r = AgentResult(answer="done", tool_calls=[ToolCall("search_docs", {}, "", 1)])
    assert not score_case(case, r).tools
