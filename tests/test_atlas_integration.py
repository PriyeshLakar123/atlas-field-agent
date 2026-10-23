"""Runs against a real Atlas cluster or the mongodb-atlas-local container.

Skipped unless ATLAS_INTEGRATION=1, so unit tests stay fast and offline.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ATLAS_INTEGRATION") != "1", reason="set ATLAS_INTEGRATION=1")


def test_ingest_and_vector_search_roundtrip():
    from pymongo import MongoClient

    from fieldagent.chunking import chunk_directory
    from fieldagent.embeddings import HashEmbedder
    from fieldagent.store import AtlasVectorStore

    uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/?directConnection=true")
    client = MongoClient(uri)
    coll = f"it_{uuid.uuid4().hex[:8]}"
    embedder = HashEmbedder()
    store = AtlasVectorStore(client, "fieldagent_test", coll, f"{coll}_ix", embedder.dimensions)
    try:
        chunks = chunk_directory("corpus")
        store.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))
        store.ensure_index(wait_seconds=180)
        import time

        hits = []
        for _ in range(30):  # newly indexed documents become searchable asynchronously
            hits = store.search(embedder.embed_query("restart the failed mongo-sink connector task"), 3)
            if hits:
                break
            time.sleep(2)
        assert hits and hits[0].source == "runbooks/kafka-consumer-lag.md"
        filtered = store.search(embedder.embed_query("severity levels"), 3, source_prefix="policies/")
        assert filtered and all(h.source.startswith("policies/") for h in filtered)
    finally:
        client["fieldagent_test"].drop_collection(coll)
