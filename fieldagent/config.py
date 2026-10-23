"""Runtime configuration, read from environment variables.

Every setting has a default that works for the local docker compose stack,
so `docker compose up` runs without a .env file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str = field(default_factory=lambda: _env("MONGODB_URI", "mongodb://localhost:27017/?directConnection=true"))
    db_name: str = field(default_factory=lambda: _env("FIELDAGENT_DB", "fieldagent"))
    collection: str = field(default_factory=lambda: _env("FIELDAGENT_COLLECTION", "chunks"))
    index_name: str = field(default_factory=lambda: _env("FIELDAGENT_INDEX", "chunks_vector_index"))

    # "voyage" calls Voyage AI; "hash" is a deterministic local embedder for offline runs and CI.
    embedder: str = field(default_factory=lambda: _env("FIELDAGENT_EMBEDDER", "hash"))
    voyage_api_key: str | None = field(default_factory=lambda: _env("VOYAGE_API_KEY"))
    voyage_model: str = field(default_factory=lambda: _env("VOYAGE_MODEL", "voyage-3.5"))

    anthropic_api_key: str | None = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    model: str = field(default_factory=lambda: _env("FIELDAGENT_MODEL", "claude-sonnet-4-5"))

    ticket_api_url: str = field(default_factory=lambda: _env("TICKET_API_URL", "http://localhost:8080"))
    ticket_client_id: str = field(default_factory=lambda: _env("TICKET_CLIENT_ID", "field-agent"))
    ticket_client_secret: str = field(default_factory=lambda: _env("TICKET_CLIENT_SECRET", "local-dev-secret"))

    top_k: int = field(default_factory=lambda: int(_env("FIELDAGENT_TOP_K", "4")))
    max_agent_steps: int = field(default_factory=lambda: int(_env("FIELDAGENT_MAX_STEPS", "6")))


def load() -> Settings:
    return Settings()
