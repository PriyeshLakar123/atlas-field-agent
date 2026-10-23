"""Command line entry point.

  python -m fieldagent ingest [--path corpus]     chunk, embed, and load docs into Atlas
  python -m fieldagent ask "question"             run the agent once and print the trace
  python -m fieldagent eval [--retrieval-only]    run evals and write evals/report.md
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import config
from .chunking import chunk_directory
from .embeddings import from_settings

log = logging.getLogger("fieldagent")


def _store(settings, embedder):
    from pymongo import MongoClient

    from .store import AtlasVectorStore

    client = MongoClient(settings.mongodb_uri, appname="atlas-field-agent", serverSelectionTimeoutMS=10000)
    return AtlasVectorStore(client, settings.db_name, settings.collection, settings.index_name, embedder.dimensions)


def _agent(settings, embedder, store):
    from .agent import Agent, AnthropicLLM
    from .ticketing import TicketClient

    tickets = TicketClient(settings.ticket_api_url, settings.ticket_client_id, settings.ticket_client_secret)
    return Agent(
        AnthropicLLM(settings.anthropic_api_key or "", settings.model),
        embedder,
        store,
        tickets,
        top_k=settings.top_k,
        max_steps=settings.max_agent_steps,
    )


def cmd_ingest(args, settings) -> int:
    embedder = from_settings(settings)
    store = _store(settings, embedder)
    chunks = chunk_directory(args.path)
    vectors = embedder.embed_documents([c.text for c in chunks])
    written = store.upsert(chunks, vectors)
    store.ensure_index()
    print(f"ingested {len(chunks)} chunks from {args.path} ({written} written), index {settings.index_name} ready")
    return 0


def cmd_ask(args, settings) -> int:
    embedder = from_settings(settings)
    agent = _agent(settings, embedder, _store(settings, embedder))
    result = agent.ask(args.question)
    print(result.answer)
    print("\n--- trace ---")
    for t in result.tool_calls:
        status = f"ERROR {t.error}" if t.error else "ok"
        print(f"{t.name}({json.dumps(t.input)}) {t.latency_ms} ms {status}")
    print(
        f"steps={result.steps} latency={result.latency_ms} ms "
        f"tokens={result.input_tokens}+{result.output_tokens} sources={result.retrieved_sources}"
    )
    return 0


def cmd_eval(args, settings) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from evals.run import run_agent, run_retrieval, to_markdown

    embedder = from_settings(settings)
    if args.in_memory:
        # Offline mode: same chunks and embeddings, cosine search in memory, no MongoDB needed.
        from .store import InMemoryVectorStore

        store = InMemoryVectorStore()
        chunks = chunk_directory(args.path)
        store.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))
    else:
        store = _store(settings, embedder)
    retrieval = run_retrieval(embedder, store, k=settings.top_k)
    agent = None if args.retrieval_only else run_agent(_agent(settings, embedder, store))
    report = to_markdown(retrieval, agent)
    out = Path(args.out)
    out.write_text(report)
    out.with_suffix(".json").write_text(json.dumps({"retrieval": retrieval, "agent": agent}, indent=2))
    print(report)
    if retrieval["recall_at_k"] < args.min_recall:
        print(f"retrieval recall {retrieval['recall_at_k']} below threshold {args.min_recall}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="fieldagent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("--path", default="corpus")
    p = sub.add_parser("ask")
    p.add_argument("question")
    p = sub.add_parser("eval")
    p.add_argument("--retrieval-only", action="store_true")
    p.add_argument("--in-memory", action="store_true", help="retrieval eval without MongoDB")
    p.add_argument("--path", default="corpus")
    p.add_argument("--out", default="evals/report.md")
    p.add_argument("--min-recall", type=float, default=0.8)
    args = parser.parse_args(argv)
    settings = config.load()
    return {"ingest": cmd_ingest, "ask": cmd_ask, "eval": cmd_eval}[args.cmd](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
