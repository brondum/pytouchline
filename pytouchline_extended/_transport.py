"""Shared internal HTTP, XML, and CGI transport helpers for Roth Touchline."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
import logging
import math
from typing import Any
from urllib.parse import quote
import xml.etree.ElementTree as ET

import cchardet as chardet  # type: ignore[import-untyped]
import httpx
from httpx import AsyncClient

logger = logging.getLogger(__name__)

READ_PATH = "/cgi-bin/ILRReadValues.cgi"
WRITE_PATH = "/cgi-bin/writeVal.cgi"
XML_HEADERS: dict[str, str] = {"Content-Type": "text/xml"}
TEMP_SCALE = 100

PARSE_ERRORS = (AttributeError, IndexError, TypeError, ValueError)
MISSING_VALUES = frozenset({None, "None", "NA", ""})


class TouchlineError(Exception):
    """Base exception for all pytouchline errors."""


class TouchlineConnectionError(TouchlineError):
    """The Touchline controller could not be reached."""


class TouchlineTimeoutError(TouchlineConnectionError):
    """The request to the Touchline controller timed out."""


class TouchlineHTTPError(TouchlineError):
    """The Touchline controller responded with a non-success HTTP status."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(f"{message} (HTTP {status_code})")
        self.status_code = status_code


class TouchlineResponseError(TouchlineError):
    """The Touchline controller returned an empty or unparseable response."""


def build_xml_item(keys: Sequence[str]) -> str:
    """Wrap parameter names into a single XML ``<i>`` request element."""
    tags = "".join(f"<n>{key}</n>" for key in keys)
    return f"<i>{tags}</i>"


def build_read_request(items: Sequence[str]) -> str:
    """Build an ``ILRReadValues.cgi`` XML request body from ``<i>`` elements."""
    joined_items = "".join(items)
    return (
        "<body>"
        "<version>1.0</version>"
        "<client>IMaster6_02_00</client>"
        "<client_ver>6.02.0006</client_ver>"
        "<file_name>room</file_name>"
        "<item_list_size>0</item_list_size>"
        f"<item_list>{joined_items}</item_list>"
        "</body>"
    )


def decode_bytes(content: bytes) -> str:
    """Decode controller bytes using UTF-8 with chardet and Windows-1252 fallback."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        detected: dict[str, Any] = chardet.detect(content)
        encoding = detected.get("encoding")
        if isinstance(encoding, str) and encoding:
            try:
                return content.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                pass
        return content.decode("cp1252", errors="replace")


def parse_xml_response(content: bytes) -> ET.Element:
    """Validate and parse raw XML response bytes without leaking response text."""
    if not content:
        raise TouchlineResponseError("Touchline controller returned empty response")
    try:
        xml_text = decode_bytes(content)
        return ET.fromstring(xml_text)
    except ET.ParseError as err:
        # Never include raw content: responses may contain controller credentials.
        raise TouchlineResponseError(
            f"Invalid XML response from Touchline controller: {err}"
        ) from err


def _consume_tag_pair(
    children: list[ET.Element], idx: int
) -> tuple[str, str | None, int]:
    """Read an ``<n>`` element at ``idx`` and pair it with a following ``<v>``."""
    raw_name = children[idx].text
    key = raw_name.strip() if raw_name else ""
    next_idx = idx + 1
    if next_idx < len(children) and children[next_idx].tag == "v":
        return key, children[next_idx].text, idx + 2
    return key, None, next_idx


def _extract_item_pairs(item: ET.Element) -> dict[str, str | None]:
    """Extract ``<n>``/``<v>`` key/value pairs from a single ``<i>`` element."""
    pairs: dict[str, str | None] = {}
    children = list(item)
    idx = 0
    while idx < len(children):
        if children[idx].tag != "n":
            idx += 1
            continue
        key, value, idx = _consume_tag_pair(children, idx)
        if key:
            pairs[key] = value
    return pairs


def parse_xml_items(response: ET.Element) -> dict[str, str | None]:
    """Parse ``<item_list>/<i>`` XML into a mapping of parameter names to values."""
    item_list = response.find("item_list")
    if item_list is None:
        raise ValueError("Missing item_list")
    items = item_list.findall("i")
    if not items:
        raise ValueError("Missing item")
    parsed: dict[str, str | None] = {}
    for item in items:
        parsed.update(_extract_item_pairs(item))
    return parsed


def scale_temperature(value: float, scale: int = TEMP_SCALE) -> int:
    """Scale a Celsius temperature into integer hundredths (e.g. ``22.5 -> 2250``)."""
    return int(round(float(value) * scale))


def matches_numeric_echo(content: bytes, expected: int | float) -> bool:
    """Check whether a ``writeVal.cgi`` response echoes the expected number."""
    text = decode_bytes(content).strip()
    if text in MISSING_VALUES:
        return False
    try:
        return math.isclose(float(text), float(expected), rel_tol=0.0, abs_tol=1e-6)
    except ValueError:
        return False


def matches_text_echo(content: bytes, expected: str) -> bool:
    """Check whether a ``writeVal.cgi`` response echoes the expected text."""
    return decode_bytes(content).rstrip("\r\n") == expected


class _TouchlineTransport:
    """Shared async HTTP/XML/CGI client for Roth Touchline controllers."""

    def __init__(
        self,
        url: str = "",
        timeout: float = 10.0,
        client: AsyncClient | None = None,
        *,
        client_factory: Callable[[], AsyncClient] | None = None,
        read_path: str = READ_PATH,
        write_path: str = WRITE_PATH,
        headers: Mapping[str, str] = XML_HEADERS,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.client = client
        self._client_factory = client_factory
        self.read_path = read_path
        self.write_path = write_path
        self.headers = dict(headers)

    def create_async_client(self) -> AsyncClient:
        """Create a default unverified ``httpx.AsyncClient``."""
        return httpx.AsyncClient(verify=False, timeout=self.timeout)

    @asynccontextmanager
    async def async_client(self) -> AsyncIterator[AsyncClient]:
        """Yield the injected client or manage a per-request client context."""
        if self.client is not None:
            yield self.client
            return
        factory = self._client_factory or self.create_async_client
        async with factory() as client:
            yield client

    async def request_async(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        """Execute an HTTP request and map transport errors to TouchlineError."""
        try:
            async with self.async_client() as client:
                return await client.request(
                    method=method, url=url, timeout=self.timeout, **kwargs
                )
        except httpx.TimeoutException as err:
            raise TouchlineTimeoutError(
                f"Touchline controller timeout after {self.timeout} seconds at {self.url}: {err}"
            ) from err
        except httpx.RequestError as err:
            raise TouchlineConnectionError(
                f"Network error connecting to Touchline controller at {self.url}: {err}"
            ) from err

    async def request_xml_async(self, payload: str) -> ET.Element:
        """POST an XML read request to ``ILRReadValues.cgi`` and parse the XML tree."""
        logger.debug(
            "Requesting URL: %s%s (timeout: %.1fs)",
            self.url,
            self.read_path,
            self.timeout,
        )
        response = await self.request_async(
            method="POST",
            url=f"{self.url}{self.read_path}",
            content=payload,
            headers=self.headers,
        )
        logger.debug(
            "Response status: %s, content length: %d bytes",
            response.status_code,
            len(response.content) if response.content else 0,
        )
        if not response.is_success:
            raise TouchlineHTTPError(
                "Roth Touchline did not respond successfully", response.status_code
            )
        return parse_xml_response(response.content)

    async def read_items_async(self, items: Sequence[str]) -> dict[str, str | None]:
        """POST ``<i>`` items and parse ``<n>``/``<v>`` pairs into a dictionary."""
        response = await self.request_xml_async(build_read_request(items))
        return parse_xml_items(response)

    async def write_parameter_async(
        self,
        key: str,
        value: str | int | float,
        *,
        error_label: str | None = None,
    ) -> bytes:
        """Write a full parameter path (e.g. ``G0.SollTemp``, ``R0.OPModeRegler``)."""
        encoded_value = quote(str(value), safe="")
        response = await self.request_async(
            method="GET",
            url=f"{self.url}{self.write_path}?{key}={encoded_value}",
        )
        if not response.is_success:
            label = error_label if error_label is not None else key
            raise TouchlineHTTPError(
                f"Failed to write parameter {label}: Roth Touchline did not respond successfully",
                response.status_code,
            )
        return response.content
