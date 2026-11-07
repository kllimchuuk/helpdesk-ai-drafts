import httpx

from delivery.exceptions import ReplyHostUnresolvedError, ReplyUrlRejectedError
from delivery.outcome import classify_error, classify_status
from delivery.schemas import SendOutcome, SendResult
from delivery.ssrf import Resolver, pin_target, system_resolve

SEND_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# No keep-alive: the pool is keyed by the pinned address, so a kept connection
# could carry a request for one host over a TLS session opened for another.
SEND_LIMITS = httpx.Limits(max_keepalive_connections=0)


def build_http_client(
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=SEND_TIMEOUT,
        limits=SEND_LIMITS,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    )


class HelpdeskClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        allowed_hosts: frozenset[str],
        resolve: Resolver = system_resolve,
    ) -> None:
        self._http = http
        self._allowed_hosts = allowed_hosts
        self._resolve = resolve

    async def send_reply(
        self, reply_url: str, *, ticket_id: str, message: str, idempotency_key: str
    ) -> SendOutcome:
        try:
            url = httpx.URL(reply_url)
            target = await pin_target(url, self._allowed_hosts, self._resolve)
        except ReplyUrlRejectedError as error:
            reason = error.payload["reason"]
            return SendOutcome(SendResult.FAILED, f"{error.code}: {reason}")
        except ReplyHostUnresolvedError as error:
            return SendOutcome(SendResult.RETRY, error.code)
        except httpx.InvalidURL:
            return SendOutcome(SendResult.FAILED, "reply_url_rejected: invalid")
        request = self._http.build_request(
            "POST",
            url.copy_with(host=target.address),
            json={"ticket_id": ticket_id, "message": message},
            headers={
                "Host": url.netloc.decode("ascii"),
                "Idempotency-Key": idempotency_key,
            },
            extensions={"sni_hostname": target.host} if url.scheme == "https" else {},
        )
        try:
            response = await self._http.send(request, follow_redirects=False)
        except httpx.TransportError as error:
            return classify_error(error)
        await response.aclose()
        return classify_status(response.status_code)
