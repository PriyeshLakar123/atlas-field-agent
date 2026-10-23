"""Evaluation harness.

Two levels, so the cheap one can gate every commit:

  retrieval  no LLM needed. For each question with expected sources, embeds
             the question and checks the vector search results.
             Metrics: recall@k and MRR.

  agent      runs the full tool calling agent. Checks, per case:
               facts      every must_include group has at least one match
               citation   an expected source is cited or retrieved
               tools      every expected tool was called
             Also records latency, steps, and tokens so regressions in cost
             show up next to regressions in quality.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

DATASET = Path(__file__).with_name("dataset.jsonl")


def load_cases(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# Retrieval ---------------------------------------------------------------
def run_retrieval(embedder, store, k: int = 4, cases: list[dict] | None = None) -> dict:
    # Ticket cases are excluded: their context comes from the ticket, not the question text,
    # so raw question retrieval is not a fair test for them. The agent eval covers those.
    cases = [c for c in (cases or load_cases()) if c.get("expected_sources") and c["kind"] == "docs"]
    rows = []
    for c in cases:
        hits = store.search(embedder.embed_query(c["question"]), k)
        ranked = []
        for h in hits:
            if h.source not in ranked:
                ranked.append(h.source)
        expected = set(c["expected_sources"])
        found = expected & set(ranked)
        first = next((i for i, s in enumerate(ranked, 1) if s in expected), None)
        rows.append(
            {
                "id": c["id"],
                "recall": len(found) / len(expected),
                "rr": 1 / first if first else 0.0,
                "top": ranked[:3],
                "expected": sorted(expected),
            }
        )
    return {
        "k": k,
        "cases": len(rows),
        "recall_at_k": round(statistics.mean(r["recall"] for r in rows), 3),
        "mrr": round(statistics.mean(r["rr"] for r in rows), 3),
        "misses": [r for r in rows if r["recall"] < 1],
    }


# Agent -------------------------------------------------------------------
@dataclass
class CaseResult:
    id: str
    kind: str
    passed: bool
    facts: bool
    citation: bool
    tools: bool
    latency_ms: int
    steps: int
    tokens: int
    tool_calls: list[str]
    answer: str


def _facts_ok(answer: str, groups: list[list[str]]) -> bool:
    low = answer.lower()
    return all(any(term.lower() in low for term in group) for group in groups)


def score_case(case: dict, result) -> CaseResult:
    facts = _facts_ok(result.answer, case.get("must_include", []))
    expected_sources = case.get("expected_sources", [])
    citation = not expected_sources or any(
        s in result.answer or s in result.retrieved_sources for s in expected_sources
    )
    called = [t.name for t in result.tool_calls]
    tools = all(t in called for t in case.get("expected_tools", []))
    return CaseResult(
        id=case["id"],
        kind=case["kind"],
        passed=facts and citation and tools and not result.stopped_early,
        facts=facts,
        citation=citation,
        tools=tools,
        latency_ms=result.latency_ms,
        steps=result.steps,
        tokens=result.input_tokens + result.output_tokens,
        tool_calls=called,
        answer=result.answer,
    )


def run_agent(agent, cases: list[dict] | None = None) -> dict:
    results = [score_case(c, agent.ask(c["question"])) for c in (cases or load_cases())]
    by_kind: dict[str, list[CaseResult]] = {}
    for r in results:
        by_kind.setdefault(r.kind, []).append(r)
    lat = sorted(r.latency_ms for r in results)
    return {
        "cases": len(results),
        "pass_rate": round(sum(r.passed for r in results) / len(results), 3),
        "by_kind": {k: round(sum(r.passed for r in v) / len(v), 3) for k, v in by_kind.items()},
        "latency_p50_ms": lat[len(lat) // 2],
        "latency_p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))],
        "avg_tokens": int(statistics.mean(r.tokens for r in results)),
        "failures": [asdict(r) for r in results if not r.passed],
        "results": [asdict(r) for r in results],
    }


def to_markdown(retrieval: dict | None, agent: dict | None) -> str:
    lines = ["# Eval report", ""]
    if retrieval:
        lines += [
            "## Retrieval",
            f"- cases: {retrieval['cases']}",
            f"- recall@{retrieval['k']}: {retrieval['recall_at_k']}",
            f"- MRR: {retrieval['mrr']}",
        ]
        for m in retrieval["misses"]:
            lines.append(f"- miss {m['id']}: expected {m['expected']}, got {m['top']}")
        lines.append("")
    if agent:
        lines += [
            "## Agent",
            f"- cases: {agent['cases']}",
            f"- pass rate: {agent['pass_rate']}",
            f"- by kind: {agent['by_kind']}",
            f"- latency p50 / p95: {agent['latency_p50_ms']} ms / {agent['latency_p95_ms']} ms",
            f"- avg tokens per question: {agent['avg_tokens']}",
        ]
        for f in agent["failures"]:
            lines.append(
                f"- FAIL {f['id']} facts={f['facts']} citation={f['citation']} tools={f['tools']} called={f['tool_calls']}"
            )
    return "\n".join(lines) + "\n"
