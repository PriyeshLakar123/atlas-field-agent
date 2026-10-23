import httpx
import pytest

from fieldagent.ticketing import TicketAPIError, TicketClient


class FakeAPI:
    """Scriptable ticket API: queue up responses per path."""

    def __init__(self):
        self.token_calls = 0
        self.requests: list[httpx.Request] = []
        self.queue: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/oauth/token":
            self.token_calls += 1
            return httpx.Response(200, json={"access_token": f"tok{self.token_calls}", "expires_in": 300})
        if self.queue:
            return self.queue.pop(0)
        return httpx.Response(200, json={"id": "INC-1", "auth": request.headers["Authorization"]})


def make(api: FakeAPI, **kw) -> TicketClient:
    sleeps: list[float] = []
    client = TicketClient("http://t", "id", "secret", transport=httpx.MockTransport(api.handler), sleep=sleeps.append, **kw)
    client.sleeps = sleeps
    return client


def test_token_is_cached_across_requests():
    api = FakeAPI()
    c = make(api)
    c.get_ticket("INC-1")
    c.get_ticket("INC-1")
    assert api.token_calls == 1


def test_401_refreshes_token_once_and_retries():
    api = FakeAPI()
    api.queue = [httpx.Response(401, json={"error": "invalid_token"})]
    c = make(api)
    body = c.get_ticket("INC-1")
    assert api.token_calls == 2
    assert body["auth"] == "Bearer tok2"


def test_repeated_401_raises_with_correlation_id():
    api = FakeAPI()
    api.queue = [httpx.Response(401), httpx.Response(401)]
    c = make(api)
    with pytest.raises(TicketAPIError) as err:
        c.get_ticket("INC-1")
    assert err.value.status == 401 and err.value.correlation_id


def test_503_retries_with_retry_after():
    api = FakeAPI()
    api.queue = [httpx.Response(503, headers={"Retry-After": "3"}), httpx.Response(503)]
    c = make(api, backoff_base=0.5)
    assert c.get_ticket("INC-1")["id"] == "INC-1"
    assert c.sleeps == [3.0, 1.0]


def test_gives_up_after_max_retries():
    api = FakeAPI()
    api.queue = [httpx.Response(503)] * 5
    c = make(api, max_retries=2)
    with pytest.raises(TicketAPIError):
        c.get_ticket("INC-1")


def test_404_is_a_result_not_an_exception():
    api = FakeAPI()
    api.queue = [httpx.Response(404)]
    assert make(api).get_ticket("INC-404") == {"error": "not_found"}


def test_correlation_id_is_constant_across_retries():
    api = FakeAPI()
    api.queue = [httpx.Response(503)]
    make(api).get_ticket("INC-1")
    ids = {r.headers["X-Correlation-ID"] for r in api.requests if r.url.path != "/oauth/token"}
    assert len(ids) == 1
