from __future__ import annotations

import asyncio
import socket
import struct
from typing import cast

import pytest

from pytouchline_extended import (
    DiscoveredController,
    TouchlineConnectionError,
    discover_controllers,
)
from pytouchline_extended._discovery import (
    DISCOVERY_REQUEST,
    DISCOVERY_RESPONSE_SIZE,
    parse_discovery_response,
)


def _build_response(
    *,
    controller_id: int = 37,
    vendor_id: int = 32,
    ip_address: str = "192.168.1.14",
    mac_address: bytes = bytes.fromhex("5CC213008149"),
    name: bytes = b"ID10655-47951974",
    location: bytes = b"http://192.168.1.14/",
    unique_id: bytes = bytes.fromhex("51FF6E064965525706340287"),
) -> bytes:
    """Build a reply with the layout and values of a real controller's answer."""
    data = bytearray(DISCOVERY_RESPONSE_SIZE)
    data[0:4] = b"R100"
    struct.pack_into(">HHH", data, 4, DISCOVERY_RESPONSE_SIZE, controller_id, vendor_id)
    data[12:16] = socket.inet_aton(ip_address)
    data[16:20] = socket.inet_aton("192.168.1.1")
    data[20:24] = socket.inet_aton("255.255.255.0")
    data[24:28] = socket.inet_aton("192.168.1.1")
    data[32:38] = mac_address
    data[48:68] = name.ljust(20, b"\0")
    data[68:148] = location.ljust(80, b"\0")
    data[148:160] = unique_id
    return bytes(data)


EXPECTED = DiscoveredController(
    controller_id=37,
    unique_id="51FF6E064965525706340287",
    url="http://192.168.1.14",
    ip_address="192.168.1.14",
    mac_address="5C-C2-13-00-81-49",
    name="ID10655-47951974",
    protocol_version="R100",
)


def test_parse_response() -> None:
    assert parse_discovery_response(_build_response()) == EXPECTED


def test_parse_response_without_location_uses_ip() -> None:
    controller = parse_discovery_response(_build_response(location=b"", name=b""))

    assert controller is not None
    assert controller.url == "http://192.168.1.14"
    assert controller.name is None


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(_build_response(vendor_id=7), id="other-vendor"),
        pytest.param(_build_response()[:-1], id="too-short"),
        pytest.param(DISCOVERY_REQUEST, id="search-request"),
    ],
)
def test_parse_response_ignores_other_packets(data: bytes) -> None:
    assert parse_discovery_response(data) is None


class _FakeController(asyncio.DatagramProtocol):
    """Answer every search with the given replies, like a controller on the LAN."""

    def __init__(self, replies: list[bytes]) -> None:
        self.replies = replies
        self.transport: asyncio.DatagramTransport | None = None
        self.requests: list[bytes] = []

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.requests.append(data)
        assert self.transport is not None
        for reply in self.replies:
            self.transport.sendto(reply, addr)


async def _start_fake_controller(
    replies: list[bytes],
) -> tuple[asyncio.DatagramTransport, _FakeController, int]:
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: _FakeController(replies), local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    return transport, protocol, port


async def test_discover_controllers() -> None:
    other = _build_response(
        controller_id=12,
        ip_address="192.168.1.20",
        location=b"http://192.168.1.20/",
        unique_id=bytes(range(12)),
    )
    replies = [
        _build_response(),
        _build_response(),  # duplicate answer from the same controller
        _build_response(vendor_id=7),  # another vendor's device
        other,
    ]
    transport, fake, port = await _start_fake_controller(replies)
    try:
        controllers = await discover_controllers(
            timeout=0.2, broadcast_address="127.0.0.1", port=port
        )
    finally:
        transport.close()

    assert fake.requests == [DISCOVERY_REQUEST]
    assert sorted(controllers, key=lambda c: c.controller_id) == [
        parse_discovery_response(other),
        EXPECTED,
    ]


async def test_discover_controllers_without_answers() -> None:
    transport, _, port = await _start_fake_controller([])
    try:
        controllers = await discover_controllers(
            timeout=0.1, broadcast_address="127.0.0.1", port=port
        )
    finally:
        transport.close()

    assert controllers == []


async def test_discover_controllers_socket_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def _fail(*args: object, **kwargs: object) -> None:
        raise OSError("no network")

    monkeypatch.setattr(loop, "create_datagram_endpoint", _fail)

    with pytest.raises(TouchlineConnectionError, match="no network"):
        await discover_controllers(timeout=0.1)
