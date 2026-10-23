# Atlas Field Agent

A support engineering agent deployed into a (fictional) customer's environment: it answers on call questions from the customer's runbooks using **MongoDB Atlas Vector Search**, and reads their **ticketing system through an OAuth2 integration**. It ships with an eval harness, a fault injecting mock of the customer API, and CI that runs against Atlas Local.

The point of the project is the deployment work around the model, not the model call: getting retrieval right on real docs, integrating with an enterprise API that fails in realistic ways, and measuring quality before and after every change.

## The customer scenario

Northwind Logistics (invented) runs a shipment API, a Kafka to MongoDB events pipeline, and a carrier integration gateway. Their on call engineers lose time hunting through runbooks and cross referencing tickets during incidents. Success criteria agreed for the pilot:

1. Answers cite the runbook they came from, so engineers can verify before acting.
2. The agent can pull live ticket context (status, notes, severity) without anyone pasting it in.
3. When the docs or tickets do not contain the answer, the agent says so instead of guessing.
4. Quality is measured on a fixed question set, and regressions block a merge.

## Architecture

```
            question
               |
        +------v-------+      search_docs       +-------------------------+
        |  Agent loop  | ---------------------> | Atlas Vector Search     |
        |  (Claude,    |                        | $vectorSearch + filter  |
        |  tool use)   |      get_ticket        +-------------------------+
        |              | ---------------------> +-------------------------+
        +--------------+      list_tickets      | Ticketing API (OAuth2   |
               |                                | client credentials)     |
         answer + trace                         +-------------------------+
```

| Path | What it does |
| --- | --- |
| `fieldagent/chunking.py` | Markdown aware chunking that keeps the heading trail in every chunk |
| `fieldagent/embeddings.py` | Voyage AI embeddings, plus a deterministic offline embedder for CI |
| `fieldagent/store.py` | Atlas Vector Search store: index creation, readiness wait, upserts, filtered `$vectorSearch` |
| `fieldagent/ticketing.py` | OAuth2 client: token caching, 401 refresh, backoff on 429/5xx, correlation ids |
| `fieldagent/agent.py` | Tool calling loop with a step limit and a full trace (tools, latency, tokens) |
| `mock_ticketing/app.py` | Stand in for the customer API, with short token TTLs and injectable 503s |
| `evals/` | 19 case dataset and harness: retrieval metrics and end to end agent checks |
| `corpus/` | Sample runbooks, architecture docs, and escalation policy |

## Run it

Local stack (Atlas Local, mock ticketing API, agent):

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY
docker compose up -d atlas tickets
docker compose run --rm agent ingest
docker compose run --rm agent ask "What's the status of INC-1042 and what should on call do next?"
docker compose run --rm agent eval
```

Against an Atlas cluster instead: set `MONGODB_URI` to your `mongodb+srv://` string and run the same commands with `python -m fieldagent ...` after `pip install -r requirements.txt`.

Offline, no keys or database:

```bash
pip install -r requirements-dev.txt
pytest -q
python -m fieldagent eval --retrieval-only --in-memory
```

## Design decisions and tradeoffs

**Chunk by heading, keep the trail.** Runbooks are short sections under descriptive headings ("Runbook: events-pipeline consumer lag > Mitigation"). Prefixing each chunk with its heading trail carries the most useful retrieval signal into every chunk. Fixed size chunks would separate a mitigation step from the alert it belongs to.

**Metadata filter in the index, not in the prompt.** `source` is indexed as a filter field, so the agent can scope a search to `runbooks/` or `policies/` inside `$vectorSearch` instead of over fetching and filtering afterwards.

**Block on index readiness.** Atlas builds search indexes asynchronously. Querying before the index is queryable returns zero results with no error, which looks exactly like "RAG is broken". `ensure_index()` polls `list_search_indexes` until `queryable` is true.

**Integration failures go back to the model, not up the stack.** If the ticket API fails after retries, the tool returns an error with the request's correlation id. The agent can still answer from the runbooks and tell the engineer the ticket system was unavailable, and the id lets the customer find that exact request in their gateway logs.

**Retry the right things.** 401 triggers exactly one token refresh (tokens get revoked and rotated); 429 and 5xx back off exponentially and honor `Retry-After`; 404 is a normal answer ("ticket not found"), not an exception. Verified against the mock API with 30% injected 503s and a 31 second token TTL: 20 of 20 calls succeeded.

**Two eval levels.** Retrieval evals need no LLM and run on every commit in CI. Agent evals need an API key and check facts, citations, tool use, and abstention, and they record latency and tokens so cost regressions show up next to quality regressions.

**Step limit.** The loop stops after `FIELDAGENT_MAX_STEPS` (default 6). A runaway tool loop in a customer environment burns tokens and rate limit on their API.

## Results

Retrieval, offline hash embedder, 12 docs questions, k=4:

| Metric | Value |
| --- | --- |
| recall@4 | 0.958 |
| MRR | 1.0 |

The one miss (r10) needs two documents, the lag runbook and the escalation policy, and only the first is retrieved. Multi hop questions like this are what the agent loop is for: it can issue a second, narrower search with `source_prefix="policies/"`.

Agent evals: run `python -m fieldagent eval` with your key. The report lands in `evals/report.md` with pass rate by case type (docs, ticket, abstain), p50/p95 latency, and tokens per question.

## Field notes

[`docs/FIELD_NOTES.md`](docs/FIELD_NOTES.md) is the product feedback from building this: each item has what happened, how to reproduce it, and a proposed fix, written for the product and engineering teams.

## Next steps

- Hybrid search (`$rankFusion` over vector and full text) for exact tokens like ticket ids and error class names.
- Re-ranking with a Voyage reranker before passing passages to the model.
- Per tenant collections or a `tenant_id` filter field for multi customer deployments.
