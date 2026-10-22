"""Fetching a URL safely.

The server fetches whatever link it is given, so this guards against SSRF: only http(s) on the
ordinary ports, every hop's host must resolve to public addresses only, redirects are followed by
hand so each hop is checked, the connection is pinned to the checked address, and size and time
are capped.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.ingest import IngestError

ALLOWED_PORTS = {80, 443}
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/pdf")
USER_AGENT = "RecallBot/0.1 (personal learning companion)"

Resolver = Callable[[str], Awaitable[list[str]]]


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise IngestError(f"Could not find the host {host!r}.") from exc
    return sorted({str(info[4][0]) for info in infos})


def is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


@dataclass(frozen=True)
class Fetched:
    url: str  # after redirects
    content_type: str
    body: bytes


class SafeFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = 8 * 1024 * 1024,
        timeout_s: float = 15.0,
        max_redirects: int = 5,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._max_bytes = max_bytes
        self._timeout = timeout_s
        self._max_redirects = max_redirects

    async def _check(self, url: str) -> tuple[str, str]:
        """Validate one hop; return (host, the public address to connect to)."""
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme not in ("http", "https") or not host:
            raise IngestError("Only http and https links can be fetched.")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in ALLOWED_PORTS:
            raise IngestError(f"Port {port} is not allowed.")
        addresses = [host] if _is_ip(host) else await self._resolver(host)
        if not addresses or not all(is_public(a) for a in addresses):
            raise IngestError("That address is not a public website, so it was not fetched.")
        return host, addresses[0]

    async def fetch(self, url: str) -> Fetched:
        current = url
        for _ in range(self._max_redirects + 1):
            host, address = await self._check(current)
            response_url, status, headers, body = await self._get_once(current, host, address)
            if status in (301, 302, 303, 307, 308):
                location = headers.get("location")
                if not location:
                    raise IngestError("The site redirected without saying where.")
                current = urljoin(response_url, location)
                continue
            if status >= 400:
                raise IngestError(f"The site answered {status}.")
            content_type = headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and not content_type.startswith(ALLOWED_TYPES):
                raise IngestError(f"Unsupported content type {content_type!r}.")
            return Fetched(current, content_type, body)
        raise IngestError("Too many redirects.")

    async def _get_once(
        self, url: str, host: str, address: str
    ) -> tuple[str, int, httpx.Headers, bytes]:
        parts = urlsplit(url)
        # Pin the connection to the address we validated so DNS cannot change under us.
        pinned = url if _is_ip(host) or self._transport else url.replace(host, _bracket(address), 1)
        extensions = {} if _is_ip(host) or self._transport else {"sni_hostname": host}
        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(
            transport=self._transport, timeout=timeout, verify=True
        ) as client:
            try:
                async with client.stream(
                    "GET",
                    pinned,
                    headers={"Host": parts.netloc, "User-Agent": USER_AGENT, "Accept": "*/*"},
                    extensions=extensions,
                ) as response:
                    size = 0
                    chunks: list[bytes] = []
                    async for piece in response.aiter_bytes():
                        size += len(piece)
                        if size > self._max_bytes:
                            raise IngestError("The page is too large to ingest.")
                        chunks.append(piece)
                    return url, response.status_code, response.headers, b"".join(chunks)
            except httpx.TimeoutException as exc:
                raise IngestError("The site took too long to answer.") from exc
            except httpx.HTTPError as exc:
                raise IngestError(f"Could not fetch the page ({type(exc).__name__}).") from exc


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _bracket(address: str) -> str:
    return f"[{address}]" if ":" in address else address
