"""Tool calling agent loop.

The model gets three tools: search the customer's runbooks (Atlas Vector
Search) and read their ticketing system. The loop is deliberately small and
explicit so every step is visible in the trace, which is what you need when
debugging an agent inside someone else's environment.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .embeddings import Embedder
from .store import VectorStore
from .ticketing import TicketAPIError, TicketClient

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a support engineering agent for Northwind Logistics.
You answer questions from on call engineers using two sources only:
1. Northwind runbooks and architecture docs, via search_docs.
2. Northwind's ticketing system, via get_ticket and list_tickets.

Rules:
- Ground every factual claim in a tool result. If the tools do not contain the answer, say so plainly.
- Cite runbook content inline as [source] using the source path returned by search_docs.
- Cite tickets by id, for example [INC-1042].
- Prefer concrete steps and commands from the runbooks over general advice.
- Keep answers short: what to do, in order, with citations."""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_docs",
        "description": "Semantic search over Northwind runbooks and architecture docs. Returns the most relevant passages with their source path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, phrased as a question or keywords."},
                "source_prefix": {
                    "type": "string",
                    "description": "Optional folder filter, for example 'runbooks/' or 'architecture/'.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_ticket",
        "description": "Fetch one ticket by id (for example INC-1042), including status, service, severity, and notes.",
        "input_schema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
        },
    },
    {
        "name": "list_tickets",
        "description": "List tickets, optionally filtered by status (open, resolved) and service name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "resolved"]},
                "service": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
        },
    },
]


class LLM(Protocol):
    def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        """Return {'stop_reason': str, 'content': [blocks], 'usage': {...}} in Anthropic Messages format."""


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        import anthropic

        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to run the agent")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def create(self, *, system, messages, tools) -> dict:
        resp = self._client.messages.create(
            model=self._model, max_tokens=self._max_tokens, system=system, messages=messages, tools=tools
        )
        return resp.model_dump()


@dataclass
class ToolCall:
    name: str
    input: dict
    output_preview: str
    latency_ms: int
    error: str | None = None


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    retrieved_sources: list[str] = field(default_factory=list)
    steps: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stopped_early: bool = False


class Agent:
    def __init__(
        self,
        llm: LLM,
        embedder: Embedder,
        store: VectorStore,
        tickets: TicketClient | None,
        *,
        top_k: int = 4,
        max_steps: int = 6,
    ) -> None:
        self.llm = llm
        self.embedder = embedder
        self.store = store
        self.tickets = tickets
        self.top_k = top_k
        self.max_steps = max_steps

    # Tools --------------------------------------------------------------
    def _run_tool(self, name: str, args: dict, result: AgentResult) -> str:
        if name == "search_docs":
            hits = self.store.search(self.embedder.embed_query(args["query"]), self.top_k, args.get("source_prefix"))
            for h in hits:
                if h.source not in result.retrieved_sources:
                    result.retrieved_sources.append(h.source)
            return json.dumps(
                [{"source": h.source, "section": h.section, "score": round(h.score, 3), "text": h.text} for h in hits]
            )
        if self.tickets is None:
            return json.dumps({"error": "ticketing integration not configured"})
        if name == "get_ticket":
            return json.dumps(self.tickets.get_ticket(args["ticket_id"]))
        if name == "list_tickets":
            return json.dumps(self.tickets.list_tickets(args.get("status"), args.get("service"), args.get("limit", 10)))
        return json.dumps({"error": f"unknown tool {name}"})

    # Loop ---------------------------------------------------------------
    def ask(self, question: str) -> AgentResult:
        started = time.monotonic()
        result = AgentResult(answer="")
        messages: list[dict] = [{"role": "user", "content": question}]

        for step in range(1, self.max_steps + 1):
            result.steps = step
            resp = self.llm.create(system=SYSTEM_PROMPT, messages=messages, tools=TOOLS)
            usage = resp.get("usage") or {}
            result.input_tokens += usage.get("input_tokens", 0) or 0
            result.output_tokens += usage.get("output_tokens", 0) or 0
            content = resp["content"]
            messages.append({"role": "assistant", "content": content})

            tool_uses = [b for b in content if b["type"] == "tool_use"]
            if resp.get("stop_reason") != "tool_use" or not tool_uses:
                result.answer = "".join(b.get("text", "") for b in content if b["type"] == "text").strip()
                break

            tool_results = []
            for block in tool_uses:
                t0 = time.monotonic()
                error = None
                try:
                    output = self._run_tool(block["name"], block["input"], result)
                except TicketAPIError as exc:
                    # Surface integration failures to the model instead of crashing, and keep
                    # the correlation id so the customer can find the request in their logs.
                    error = f"{exc} (correlation_id={exc.correlation_id})"
                    output = json.dumps({"error": error})
                    log.warning("tool %s failed: %s", block["name"], error)
                result.tool_calls.append(
                    ToolCall(block["name"], block["input"], output[:300], int((time.monotonic() - t0) * 1000), error)
                )
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block["id"], "content": output, "is_error": error is not None}
                )
            messages.append({"role": "user", "content": tool_results})
        else:
            result.stopped_early = True
            result.answer = "Stopped after reaching the step limit without a final answer."

        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result
