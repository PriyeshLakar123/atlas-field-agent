from fieldagent.chunking import chunk_directory, chunk_markdown

DOC = """# Runbook: thing

Intro paragraph.

## Triage

Step one.

## Mitigation

Step two.
"""


def test_sections_keep_heading_trail():
    chunks = chunk_markdown(DOC, "runbooks/thing.md")
    sections = [c.section for c in chunks]
    assert sections == ["Runbook: thing", "Runbook: thing > Triage", "Runbook: thing > Mitigation"]
    assert chunks[1].text.startswith("Runbook: thing > Triage")


def test_ids_are_stable_across_runs():
    a = [c.chunk_id for c in chunk_markdown(DOC, "x.md")]
    b = [c.chunk_id for c in chunk_markdown(DOC, "x.md")]
    assert a == b and len(set(a)) == len(a)


def test_long_sections_split_with_budget():
    body = "# T\n\n" + "\n\n".join(f"paragraph {i} " + "word " * 60 for i in range(10))
    chunks = chunk_markdown(body, "long.md", max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c.text) < 900 for c in chunks)


def test_sample_corpus_loads():
    chunks = chunk_directory("corpus")
    sources = {c.source for c in chunks}
    assert "runbooks/kafka-consumer-lag.md" in sources
    assert len(chunks) > 20
