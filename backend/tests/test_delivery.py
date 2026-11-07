import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from delivery.helpdesk_client import HelpdeskClient, build_http_client
from delivery.schemas import SendResult
from delivery.ssrf import is_public

PUBLIC_IP = "93.184.216.34"
REPLY_URL = "https://helpdesk.example.com/tickets/T-1042/replies"


class Helpdesk:
    def __init__(self, respond=None) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond or (lambda request: httpx.Response(201))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


def resolver(*addresses: str, error: Exception | None = None):
    lookups: list[str] = []

    async def resolve(host: str, port: int) -> list[str]:
        lookups.append(host)
        if error is not None:
            raise error
        return list(addresses)

    resolve.lookups = lookups
    return resolve


def client(helpdesk: Helpdesk, resolve=None, allowed: frozenset[str] = frozenset()):
    return HelpdeskClient(
        build_http_client(httpx.MockTransport(helpdesk)),
        allowed_hosts=allowed,
        resolve=resolve or resolver(PUBLIC_IP),
    )


async def send(helpdesk_client: HelpdeskClient, url: str = REPLY_URL):
    return await helpdesk_client.send_reply(
        url, ticket_id="T-1042", message="Відповідь", idempotency_key="key-1"
    )


async def test_a_201_is_delivered_and_the_request_follows_the_contract() -> None:
    helpdesk = Helpdesk()

    outcome = await send(client(helpdesk))

    assert outcome.result == SendResult.DELIVERED
    [request] = helpdesk.requests
    assert request.method == "POST"
    assert request.headers["idempotency-key"] == "key-1"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "ticket_id": "T-1042",
        "message": "Відповідь",
    }


async def test_the_request_goes_to_the_checked_address_with_the_original_host() -> None:
    """DNS rebinding: no second lookup can send the request somewhere else."""
    helpdesk = Helpdesk()
    resolve = resolver(PUBLIC_IP)

    await send(client(helpdesk, resolve), "https://HelpDesk.example.com:8443/r?x=1")

    [request] = helpdesk.requests
    assert resolve.lookups == ["helpdesk.example.com"]
    assert request.url.host == PUBLIC_IP
    assert request.url.port == 8443
    assert request.url.path == "/r"
    assert request.url.query == b"x=1"
    assert request.headers["host"] == "helpdesk.example.com:8443"
    assert request.extensions["sni_hostname"] == "helpdesk.example.com"


async def test_a_plain_http_url_gets_no_sni() -> None:
    helpdesk = Helpdesk()

    await send(client(helpdesk), "http://helpdesk.example.com/r")

    assert "sni_hostname" not in helpdesk.requests[0].extensions


@pytest.mark.parametrize(
    ("status", "result"),
    [
        (201, SendResult.DELIVERED),
        (200, SendResult.UNKNOWN),
        (202, SendResult.UNKNOWN),
        (204, SendResult.UNKNOWN),
        (301, SendResult.FAILED),
        (302, SendResult.FAILED),
        (400, SendResult.FAILED),
        (401, SendResult.FAILED),
        (404, SendResult.FAILED),
        (422, SendResult.FAILED),
        (408, SendResult.RETRY),
        (429, SendResult.RETRY),
        (500, SendResult.RETRY),
        (502, SendResult.RETRY),
        (503, SendResult.RETRY),
    ],
)
async def test_statuses_are_classified(status: int, result: SendResult) -> None:
    helpdesk = Helpdesk(lambda request: httpx.Response(status))

    outcome = await send(client(helpdesk))

    assert outcome.result == result
    assert outcome.detail == f"HTTP {status}"


async def test_a_redirect_is_not_followed() -> None:
    helpdesk = Helpdesk(
        lambda request: httpx.Response(302, headers={"location": "http://10.0.0.1/"})
    )

    outcome = await send(client(helpdesk))

    assert outcome.result == SendResult.FAILED
    assert len(helpdesk.requests) == 1


@pytest.mark.parametrize(
    ("error", "result"),
    [
        (httpx.ConnectError("refused"), SendResult.RETRY),
        (httpx.ConnectTimeout("slow"), SendResult.RETRY),
        (httpx.PoolTimeout("busy"), SendResult.RETRY),
        (httpx.ReadTimeout("hang"), SendResult.UNKNOWN),
        (httpx.WriteTimeout("slow body"), SendResult.UNKNOWN),
        (httpx.ReadError("reset"), SendResult.UNKNOWN),
        (httpx.WriteError("broken pipe"), SendResult.UNKNOWN),
        (httpx.RemoteProtocolError("dropped"), SendResult.UNKNOWN),
    ],
)
async def test_transport_errors_are_definite_only_before_sending(
    error: Exception, result: SendResult
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error

    outcome = await send(client(Helpdesk(fail)))

    assert outcome.result == result
    assert outcome.detail == type(error).__name__


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
async def test_a_private_address_is_refused_without_a_request(address: str) -> None:
    helpdesk = Helpdesk()

    outcome = await send(client(helpdesk, resolver(address)))

    assert outcome.result == SendResult.FAILED
    assert outcome.detail == "reply_url_rejected: address"
    assert helpdesk.requests == []


async def test_one_private_address_among_public_ones_is_enough_to_refuse() -> None:
    helpdesk = Helpdesk()

    outcome = await send(client(helpdesk, resolver(PUBLIC_IP, "10.0.0.1")))

    assert outcome.result == SendResult.FAILED
    assert helpdesk.requests == []


async def test_an_allowed_host_may_resolve_to_a_private_address() -> None:
    helpdesk = Helpdesk()

    outcome = await send(
        client(helpdesk, resolver("172.18.0.5"), frozenset({"mock-helpdesk"})),
        "http://Mock-Helpdesk:8000/tickets/T-1/replies",
    )

    assert outcome.result == SendResult.DELIVERED
    assert helpdesk.requests[0].url.host == "172.18.0.5"
    assert helpdesk.requests[0].headers["host"] == "mock-helpdesk:8000"


@pytest.mark.parametrize(
    "error", [OSError("no such host"), TimeoutError(), UnicodeError("idna")]
)
async def test_an_unresolvable_host_is_a_definite_failure(error: Exception) -> None:
    helpdesk = Helpdesk()

    outcome = await send(client(helpdesk, resolver(error=error)))

    assert outcome.result == SendResult.RETRY
    assert outcome.detail == "reply_host_unresolved"
    assert helpdesk.requests == []


async def test_an_empty_lookup_is_a_definite_failure() -> None:
    outcome = await send(client(Helpdesk(), resolver()))

    assert outcome.result == SendResult.RETRY


@pytest.mark.parametrize(
    "url",
    ["ftp://helpdesk.example.com/r", "file:///etc/passwd", "not a url", "http://"],
)
async def test_unusable_urls_are_refused(url: str) -> None:
    helpdesk = Helpdesk()

    outcome = await send(client(helpdesk), url)

    assert outcome.result == SendResult.FAILED
    assert helpdesk.requests == []


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("8.8.8.8", True),
        ("2606:4700::1111", True),
        ("10.1.1.1", False),
        ("::ffff:8.8.8.8", True),
        ("x", False),
    ],
)
def test_is_public(address: str, public: bool) -> None:
    assert is_public(address) is public


async def test_a_send_slower_than_the_deadline_is_ambiguous() -> None:
    """A hostile server trickling bytes must not hold a send past its lease."""

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(201)

    helpdesk_client = HelpdeskClient(
        build_http_client(httpx.MockTransport(stall)),
        allowed_hosts=frozenset(),
        resolve=resolver(PUBLIC_IP),
        deadline_seconds=0.1,
    )

    outcome = await send(helpdesk_client)

    assert outcome.result == SendResult.UNKNOWN
    assert outcome.detail == "send_deadline"


async def test_the_response_body_is_never_read() -> None:
    async def endless() -> AsyncIterator[bytes]:
        yield b"x"
        raise httpx.ReadError("the body never ends")

    helpdesk = Helpdesk(lambda request: httpx.Response(201, content=endless()))

    outcome = await send(client(helpdesk))

    assert outcome.result == SendResult.DELIVERED


@pytest.mark.parametrize("address", ["64:ff9b::a00:1", "64:ff9b:1::a00:1"])
def test_nat64_addresses_are_not_public(address: str) -> None:
    """Through a NAT64 gateway these reach the embedded IPv4 address, e.g. 10.0.0.1."""
    assert is_public(address) is False
