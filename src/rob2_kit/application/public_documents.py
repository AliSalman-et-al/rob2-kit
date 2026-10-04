"""Bounded HTTPX reads on vetted provider-controlled public HTTPS hosts."""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

PUBLIC_DOCUMENT_HOSTS = frozenset(
    {
        "cdn.clinicaltrials.gov",
        "journals.plos.org",
        "pmc.ncbi.nlm.nih.gov",
    }
)
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def _validate_url(url: str, hosts: frozenset[str]) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("unsupported_or_forbidden_public_url")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("nonpublic_destination")


def fetch_bounded(
    client: httpx.Client,
    url: str,
    hosts: frozenset[str],
    limit: int,
    chain: list[str],
    max_requests: int = 4,
) -> bytes:
    for _ in range(max_requests):
        _validate_url(url, hosts)
        client.cookies.clear()
        chain.append(url)
        with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise ValueError("redirect_without_destination")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").casefold() != "identity":
                raise ValueError("unsupported_content_encoding")
            chunks = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise ValueError("document_size_limit")
            return bytes(chunks)
    raise ValueError("redirect_limit")
