"""Embedding providers.

VoyageEmbedder is the production path. HashEmbedder is a deterministic,
dependency free fallback so ingestion, retrieval evals, and CI run with no
API keys. It is a feature hashing bag of words model: weak semantics, but
stable and good enough to test the pipeline end to end.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

import httpx

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be",
    "it", "this", "that", "with", "as", "by", "at", "from", "how", "what", "do", "i",
    "we", "our", "my", "can", "should", "when", "if", "does", "which", "you", "your",
}


class Embedder(Protocol):
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class HashEmbedder:
    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for gram in grams:
            digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        return _normalize(vec)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class VoyageEmbedder:
    """Voyage AI embeddings over plain HTTP (no SDK dependency)."""

    _DIMS = {"voyage-3.5": 1024, "voyage-3.5-lite": 1024, "voyage-3-large": 1024}

    def __init__(self, api_key: str, model: str = "voyage-3.5", batch_size: int = 64) -> None:
        if not api_key:
            raise ValueError("VOYAGE_API_KEY is required when FIELDAGENT_EMBEDDER=voyage")
        self.model = model
        self.dimensions = self._DIMS.get(model, 1024)
        self.batch_size = batch_size
        self._client = httpx.Client(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    def _call(self, texts: Sequence[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = list(texts[i : i + self.batch_size])
            resp = self._client.post(
                "/embeddings", json={"input": batch, "model": self.model, "input_type": input_type}
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return out

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._call(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._call([text], "query")[0]


def from_settings(settings) -> Embedder:
    if settings.embedder == "voyage":
        return VoyageEmbedder(settings.voyage_api_key or "", settings.voyage_model)
    if settings.embedder == "hash":
        return HashEmbedder()
    raise ValueError(f"Unknown FIELDAGENT_EMBEDDER: {settings.embedder!r}")
