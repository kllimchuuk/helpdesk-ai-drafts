import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

import httpx

from delivery.exceptions import ReplyHostUnresolvedError, ReplyUrlRejectedError
from delivery.schemas import PinnedTarget

Resolver = Callable[[str, int], Awaitable[list[str]]]

ALLOWED_SCHEMES = ("http", "https")
RESOLVE_TIMEOUT_S = 5.0
NAT64_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


async def system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


async def pin_target(
    url: httpx.URL, allowed_hosts: frozenset[str], resolve: Resolver
) -> PinnedTarget:
    if url.scheme not in ALLOWED_SCHEMES:
        raise ReplyUrlRejectedError("scheme")
    host = url.raw_host.decode("ascii").lower()
    if not host:
        raise ReplyUrlRejectedError("host")
    try:
        async with asyncio.timeout(RESOLVE_TIMEOUT_S):
            addresses = await resolve(host, url.port or default_port(url.scheme))
    except (OSError, TimeoutError, UnicodeError):
        raise ReplyHostUnresolvedError() from None
    if not addresses:
        raise ReplyHostUnresolvedError()
    if host not in allowed_hosts and not all(map(is_public, addresses)):
        raise ReplyUrlRejectedError("address")
    return PinnedTarget(host=host, address=addresses[0])


def is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if any(ip in network for network in NAT64_NETWORKS):
        return False
    return ip.is_global and not ip.is_multicast


def default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80
