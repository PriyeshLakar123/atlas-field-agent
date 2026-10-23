"""Stand in for the customer's ticketing system.

Implements just enough of a real enterprise API to exercise the integration:
an OAuth2 client credentials token endpoint, bearer token checks, short
token lifetimes, and optional fault injection for testing retries.

Fault injection (env vars):
  MOCK_TOKEN_TTL       token lifetime in seconds (default 300)
  MOCK_FAIL_RATE       fraction of ticket requests that return 503 (default 0)
"""
from __future__ import annotations

import os
import random
import secrets
import time

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

CLIENT_ID = os.environ.get("TICKET_CLIENT_ID", "field-agent")
CLIENT_SECRET = os.environ.get("TICKET_CLIENT_SECRET", "local-dev-secret")
TOKEN_TTL = int(os.environ.get("MOCK_TOKEN_TTL", "300"))
FAIL_RATE = float(os.environ.get("MOCK_FAIL_RATE", "0"))

app = FastAPI(title="Northwind Ticketing (mock)")
basic = HTTPBasic()
_tokens: dict[str, float] = {}

TICKETS = {
    "INC-1042": {
        "id": "INC-1042", "status": "open", "severity": "Sev 2", "service": "shipment-api",
        "title": "Tracking page p99 latency above 1.2s",
        "opened_at": "2026-10-21T15:02:00Z",
        "notes": [
            "ShipmentApiP99High fired at 15:00 UTC. Only GET /shipments/{id}/tracking is slow.",
            "Query Insights shows COLLSCAN on shipping.shipments for carrierId + status queries.",
        ],
    },
    "INC-1043": {
        "id": "INC-1043", "status": "open", "severity": "Sev 2", "service": "events-pipeline",
        "title": "events-sink lag at 180k messages",
        "opened_at": "2026-10-22T09:40:00Z",
        "notes": ["mongo-sink task 0 is FAILED with BsonMaximumSizeExceededException."],
    },
    "INC-1038": {
        "id": "INC-1038", "status": "resolved", "severity": "Sev 1", "service": "shipment-api",
        "title": "503s on shipment creation",
        "opened_at": "2026-10-14T18:10:00Z",
        "notes": [
            "MongoWaitQueueTimeoutError across all shipment-api pods.",
            "Root cause: release 4.12 set maxPoolSize=400 while replicas scaled to 10. Reverted to 50.",
        ],
    },
    "INC-1045": {
        "id": "INC-1045", "status": "open", "severity": "Sev 3", "service": "partner-gateway",
        "title": "No tracking updates from carrier BlueLine since 06:00 UTC",
        "opened_at": "2026-10-23T06:20:00Z",
        "notes": ["partner-gateway logs 401 invalid_client for BlueLine. Carrier rotated secrets on 2026-10-22."],
    },
}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/oauth/token")
def token(grant_type: str = Form(...), scope: str = Form(""), creds: HTTPBasicCredentials = Depends(basic)) -> dict:
    if grant_type != "client_credentials":
        raise HTTPException(400, detail={"error": "unsupported_grant_type"})
    ok = secrets.compare_digest(creds.username, CLIENT_ID) and secrets.compare_digest(creds.password, CLIENT_SECRET)
    if not ok:
        raise HTTPException(401, detail={"error": "invalid_client"})
    tok = secrets.token_urlsafe(24)
    _tokens[tok] = time.time() + TOKEN_TTL
    return {"access_token": tok, "token_type": "Bearer", "expires_in": TOKEN_TTL, "scope": scope}


def require_token(authorization: str = Header(default="")) -> None:
    tok = authorization.removeprefix("Bearer ").strip()
    if not tok or _tokens.get(tok, 0) < time.time():
        raise HTTPException(401, detail={"error": "invalid_token"})


def maybe_fail(request: Request) -> None:
    if FAIL_RATE and random.random() < FAIL_RATE:
        raise HTTPException(503, detail="injected failure", headers={"Retry-After": "1"})


@app.get("/api/tickets", dependencies=[Depends(require_token), Depends(maybe_fail)])
def list_tickets(status: str | None = None, service: str | None = None, limit: int = 10) -> dict:
    rows = [t for t in TICKETS.values() if (not status or t["status"] == status) and (not service or t["service"] == service)]
    rows.sort(key=lambda t: t["opened_at"], reverse=True)
    return {"tickets": [{k: t[k] for k in ("id", "status", "severity", "service", "title")} for t in rows[:limit]]}


@app.get("/api/tickets/{ticket_id}", dependencies=[Depends(require_token), Depends(maybe_fail)])
def get_ticket(ticket_id: str) -> dict:
    if ticket_id not in TICKETS:
        raise HTTPException(404, detail={"error": "not_found"})
    return TICKETS[ticket_id]
