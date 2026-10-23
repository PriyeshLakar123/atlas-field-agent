# Field notes

Product feedback captured while building and deploying the agent. Format per item: behavior, how to reproduce, impact, proposed path forward.

## 1. Vector search returns nothing right after index creation

**Behavior.** Search indexes build asynchronously. A `$vectorSearch` sent before the index is queryable returns an empty cursor with no error, so the agent answers "I couldn't find that in the runbooks".

**Reproduce.**
1. Create a collection, insert documents with embeddings.
2. Call `create_search_index` with a `vectorSearch` definition.
3. Immediately run a `$vectorSearch` aggregation. Result: empty cursor.

**Impact.** Looks identical to a bad embedding model or a wrong `path`, so first time users debug the wrong layer.

**Workaround in this repo.** `AtlasVectorStore.ensure_index()` polls `list_search_indexes(name)` until `queryable: true` before returning.

**Proposed path forward.** Return a warning (or an opt in error) from `$vectorSearch` when the named index exists but is not yet queryable, and surface index state in driver helpers, for example `create_search_index(..., wait=True)`.

## 2. Newly written documents are searchable a moment later

**Behavior.** Search indexes sync from the collection asynchronously, so a search issued immediately after a write can miss the newest documents.

**Reproduce.** Insert into a collection with a ready vector index, then search for the new text within the same second.

**Impact.** Matters for agents that write and then read their own memory or notes in the same turn.

**Workaround.** The test retries the search for up to 60 seconds. In the agent, writes and reads are in different phases, so this does not affect answers.

**Proposed path forward.** Document the expected sync lag next to the `$vectorSearch` reference, and expose a per collection "search lag" metric in Atlas so teams can set expectations.

## 3. Prefix filters on paths need a range workaround

**Behavior.** Scoping search to a folder (`runbooks/`) needed `{"source": {"$gte": prefix, "$lt": prefix + "￿"}}` inside the `$vectorSearch` filter, since regex is not supported there.

**Impact.** Small, but every RAG deployment over a document tree hits it.

**Proposed path forward.** A short "filter by path prefix" example in the vector search filter docs, or a dedicated prefix operator.

## 4. Exact identifiers retrieve poorly with pure vector search

**Behavior.** Questions that hinge on exact tokens (`INC-1043`, `BsonMaximumSizeExceededException`) depend on the embedding model treating those tokens well.

**Workaround.** Ticket ids go through the ticket API tool, not retrieval.

**Proposed path forward.** Hybrid search (`$rankFusion` over `$vectorSearch` and `$search`) is the next change here. A first party template for "RAG over runbooks with hybrid search" would shorten this for customers.
