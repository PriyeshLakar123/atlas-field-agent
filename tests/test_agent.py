import json

from fieldagent.agent import Agent
from fieldagent.chunking import chunk_directory
from fieldagent.embeddings import HashEmbedder
from fieldagent.ticketing import TicketAPIError
from fieldagent.store import InMemoryVectorStore


class ScriptedLLM:
    """Replays a fixed sequence of model turns and records what it was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def create(self, *, system, messages, tools):
        self.calls.append(json.loads(json.dumps(messages)))
        return self.turns.pop(0)


def tool_turn(name, args, id_="t1"):
    return {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": id_, "name": name, "input": args}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def text_turn(text):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}], "usage": {"input_tokens": 20, "output_tokens": 8}}


class FakeTickets:
    def __init__(self, fail=False):
        self.fail = fail

    def get_ticket(self, ticket_id):
        if self.fail:
            raise TicketAPIError("upstream 503", 503, "cid-123")
        return {"id": ticket_id, "status": "open"}

    def list_tickets(self, status=None, service=None, limit=10):
        return {"tickets": []}


def build(turns, tickets=None):
    embedder = HashEmbedder()
    store = InMemoryVectorStore()
    chunks = chunk_directory("corpus")
    store.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))
    llm = ScriptedLLM(turns)
    return Agent(llm, embedder, store, tickets or FakeTickets(), max_steps=4), llm


def test_search_then_answer_records_sources_and_tokens():
    agent, llm = build([tool_turn("search_docs", {"query": "restart failed mongo-sink task"}), text_turn("Restart it [runbooks/kafka-consumer-lag.md]")])
    result = agent.ask("how do I restart the sink?")
    assert result.answer.startswith("Restart it")
    assert "runbooks/kafka-consumer-lag.md" in result.retrieved_sources
    assert [t.name for t in result.tool_calls] == ["search_docs"]
    assert result.input_tokens == 30 and result.steps == 2
    # The tool result was sent back to the model.
    assert llm.calls[1][-1]["content"][0]["type"] == "tool_result"


def test_source_prefix_filter_is_applied():
    agent, _ = build([tool_turn("search_docs", {"query": "severity", "source_prefix": "policies/"}), text_turn("ok")])
    result = agent.ask("q")
    assert result.retrieved_sources and all(s.startswith("policies/") for s in result.retrieved_sources)


def test_integration_errors_go_back_to_the_model_with_correlation_id():
    agent, llm = build([tool_turn("get_ticket", {"ticket_id": "INC-1"}), text_turn("The ticket system is unavailable.")], FakeTickets(fail=True))
    result = agent.ask("status of INC-1?")
    assert result.tool_calls[0].error and "cid-123" in result.tool_calls[0].error
    sent = llm.calls[1][-1]["content"][0]
    assert sent["is_error"] is True and "cid-123" in sent["content"]


def test_step_limit_stops_runaway_loops():
    agent, _ = build([tool_turn("list_tickets", {}, id_=f"t{i}") for i in range(4)])
    result = agent.ask("loop forever")
    assert result.stopped_early and result.steps == 4
