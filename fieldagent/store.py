"""Vector stores.

AtlasVectorStore uses MongoDB Atlas Vector Search ($vectorSearch). It works
against an Atlas cluster or the mongodb-atlas-local container.
InMemoryVectorStore mirrors the same interface for unit tests.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .chunking import Chunk

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    source: str
    section: str
    text: str
    score: float


class VectorStore(Protocol):
    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> int: ...

    def search(self, vector: list[float], k: int, source_prefix: str | None = None) -> list[Hit]: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._rows: dict[str, tuple[Chunk, list[float]]] = {}

    def upsert(self, chunks, vectors) -> int:
        for c, v in zip(chunks, vectors, strict=True):
            self._rows[c.chunk_id] = (c, v)
        return len(chunks)

    def search(self, vector, k, source_prefix=None) -> list[Hit]:
        def cos(a, b):
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(x * x for x in b)) or 1.0
            return sum(x * y for x, y in zip(a, b)) / (na * nb)

        scored = [
            Hit(c.chunk_id, c.source, c.section, c.text, cos(vector, v))
            for c, v in self._rows.values()
            if source_prefix is None or c.source.startswith(source_prefix)
        ]
        return sorted(scored, key=lambda h: h.score, reverse=True)[:k]


class AtlasVectorStore:
    def __init__(self, client, db_name: str, collection: str, index_name: str, dimensions: int) -> None:
        self.coll = client[db_name][collection]
        self.index_name = index_name
        self.dimensions = dimensions

    # Index management -------------------------------------------------
    def index_definition(self) -> dict:
        return {
            "fields": [
                {"type": "vector", "path": "embedding", "numDimensions": self.dimensions, "similarity": "cosine"},
                {"type": "filter", "path": "source"},
            ]
        }

    def ensure_index(self, wait_seconds: int = 120) -> None:
        """Create the vector index if missing and wait until it is queryable.

        Index builds are asynchronous on Atlas. Querying before the index is
        READY silently returns zero results, which is the most common
        "RAG returns nothing" bug in first deployments, so we block on it.
        """
        from pymongo.operations import SearchIndexModel

        existing = {ix["name"]: ix for ix in self.coll.list_search_indexes()}
        if self.index_name not in existing:
            if self.coll.name not in self.coll.database.list_collection_names():
                # The collection must exist before a search index can be created on it.
                self.coll.database.create_collection(self.coll.name)
            log.info("creating vector index %s", self.index_name)
            self.coll.create_search_index(
                SearchIndexModel(definition=self.index_definition(), name=self.index_name, type="vectorSearch")
            )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            ix = next(iter(self.coll.list_search_indexes(self.index_name)), None)
            if ix and ix.get("queryable"):
                return
            time.sleep(2)
        raise TimeoutError(f"vector index {self.index_name} not queryable after {wait_seconds}s")

    # Data -------------------------------------------------------------
    def upsert(self, chunks, vectors) -> int:
        from pymongo import ReplaceOne

        ops = [
            ReplaceOne(
                {"_id": c.chunk_id},
                {"_id": c.chunk_id, "source": c.source, "section": c.section, "text": c.text, "embedding": v},
                upsert=True,
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        if not ops:
            return 0
        result = self.coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    def search(self, vector, k, source_prefix=None) -> list[Hit]:
        stage: dict = {
            "index": self.index_name,
            "path": "embedding",
            "queryVector": vector,
            "numCandidates": max(50, k * 20),
            "limit": k,
        }
        if source_prefix:
            stage["filter"] = {"source": {"$gte": source_prefix, "$lt": source_prefix + "￿"}}
        pipeline = [
            {"$vectorSearch": stage},
            {"$project": {"source": 1, "section": 1, "text": 1, "score": {"$meta": "vectorSearchScore"}}},
        ]
        return [
            Hit(d["_id"], d["source"], d.get("section", ""), d["text"], float(d["score"]))
            for d in self.coll.aggregate(pipeline)
        ]
