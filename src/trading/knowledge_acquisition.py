"""Operator-approved public source acquisition; never a model or MCP network tool."""

import http.client
import ipaddress
import socket
import ssl
import time
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field

from trading.research_knowledge import ResearchKnowledge, SourceImport


class URLImport(SourceImport):
    text: str = "Approved source acquisition pending"
    format: Literal["text", "markdown", "html", "pdf"] = "html"
    url: str = Field(min_length=12, max_length=300)
    acquire_approved: bool = False


def public_target(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(c.isspace() or ord(c) < 32 for c in url)
    ):
        raise ValueError("Approve one exact public HTTPS document without credentials or query")
    host = parsed.hostname.encode("idna").decode()
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Source resolved to a private/reserved address; acquisition refused")
    return host, str(addresses[0][4][0])


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        self._ssl_context = ssl.create_default_context()
        super().__init__(host, timeout=5, context=self._ssl_context)
        self.address = address

    def connect(self) -> None:
        # Connect exactly the checked address while certificate/SNI/Host use its name.
        raw = socket.create_connection((self.address, 443), timeout=5)
        try:
            self.sock = self._ssl_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def acquire(knowledge: ResearchKnowledge, command: URLImport) -> dict[str, object]:
    if not command.acquire_approved or command.origin != command.url:
        raise ValueError("Explicit exact-URL acquisition and rights approval required")
    if command.format not in {"html", "text", "markdown"}:
        raise ValueError("URL import accepts bounded text/HTML; upload original PDF separately")
    host, address = public_target(command.url)
    connection = _PinnedHTTPS(host, address)
    try:
        connection.request(
            "GET",
            urlsplit(command.url).path or "/",
            headers={
                "User-Agent": "Q-Trades/knowledge-source-v1",
                "Accept-Encoding": "identity",
                "Accept": "text/plain,text/html,text/markdown",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Public source denied/redirected/unavailable; no redirect followed")
        mime = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
        expected = {
            "html": {"text/html"},
            "text": {"text/plain"},
            "markdown": {"text/markdown", "text/plain"},
        }[command.format]
        if mime not in expected or response.getheader("Content-Encoding") not in {None, "identity"}:
            raise ValueError("Source MIME/compression differs from the approved bounded section")
        deadline = time.monotonic() + 10
        payload = bytearray()
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > 65536 or time.monotonic() > deadline:
                raise ValueError("Source exceeds byte/deadline allowance; no partial import")
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("Unsupported source encoding; exact UTF-8 section required") from exc
        source = SourceImport.model_validate(
            command.model_dump(exclude={"url", "acquire_approved"}) | {"text": text}
        )
        return knowledge.ingest(source)
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError("Public source connection unavailable; original library retained") from exc
    finally:
        connection.close()
