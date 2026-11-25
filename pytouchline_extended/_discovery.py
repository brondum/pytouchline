"""UDP broadcast discovery of Roth Touchline controllers on the local network.

This is the protocol the official Roth Touchline app uses to find controllers:
a ``SEARCH R*`` broadcast to UDP port 5000, answered by every controller with a
160-byte binary description of itself, sent back to the sender's port.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import socket
import struct
from typing import Any

from ._transport import TouchlineConnectionError

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 5000
DISCOVERY_REQUEST = b"SEARCH R*\r\n"
DISCOVERY_RESPONSE_SIZE = 160
DEFAULT_DISCOVERY_TIMEOUT = 3.0
ROTH_VENDOR_ID = 32

# Layout of the 160-byte reply (all integers are big-endian):
#   0-3     protocol version, ASCII (e.g. "R100")
#   4-5     reply length
#   6-7     device ID (the controller's short ID, ``R0.kurzID``)
#   8-9     vendor ID (Roth = 32)
#   12-31   IPv4 address, gateway, netmask, primary DNS, secondary DNS
#   32-37   MAC address
#   48-67   name, ISO-8859-1, NUL padded
#   68-147  location (the controller's base URL), ASCII, NUL padded
#   148-159 unique ID (the controller's serial number, ``R0.uniqueID``)


@dataclass(frozen=True)
class DiscoveredController:
    """A Roth Touchline controller that answered a discovery broadcast."""

    controller_id: int
    unique_id: str
    url: str
    ip_address: str
    mac_address: str
    name: str | None
    protocol_version: str


def _decode_text(raw: bytes, encoding: str) -> str:
    """Decode a NUL-padded text field."""
    return raw.split(b"\0", 1)[0].decode(encoding, errors="replace").strip()


def parse_discovery_response(data: bytes) -> DiscoveredController | None:
    """Parse a discovery reply, or return ``None`` if it is not from a Roth controller."""
    if len(data) != DISCOVERY_RESPONSE_SIZE:
        return None
    (vendor_id,) = struct.unpack_from(">H", data, 8)
    if vendor_id != ROTH_VENDOR_ID:
        return None

    (controller_id,) = struct.unpack_from(">H", data, 6)
    ip_address = socket.inet_ntoa(data[12:16])
    location = _decode_text(data[68:148], "ascii").rstrip("/")
    return DiscoveredController(
        controller_id=controller_id,
        unique_id=data[148:160].hex().upper(),
        url=location or f"http://{ip_address}",
        ip_address=ip_address,
        mac_address="-".join(f"{byte:02X}" for byte in data[32:38]),
        name=_decode_text(data[48:68], "iso-8859-1") or None,
        protocol_version=_decode_text(data[0:4], "ascii"),
    )


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Collect discovery replies, keyed by the controller's unique ID."""

    def __init__(self) -> None:
        self.controllers: dict[str, DiscoveredController] = {}

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        controller = parse_discovery_response(data)
        if controller is None:
            return
        logger.debug("Discovered Touchline controller %s at %s", controller, addr)
        self.controllers.setdefault(controller.unique_id, controller)

    def error_received(self, exc: Exception) -> None:
        logger.debug("Error while discovering Touchline controllers: %s", exc)


async def discover_controllers(
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    broadcast_address: str = "255.255.255.255",
    port: int = DISCOVERY_PORT,
) -> list[DiscoveredController]:
    """Broadcast a search and return the controllers that answer within ``timeout``.

    ``broadcast_address`` can be set to a subnet's broadcast address (e.g.
    ``192.168.1.255``) on hosts with several network interfaces, where the
    limited broadcast address only reaches one of them.
    """
    loop = asyncio.get_running_loop()
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            _DiscoveryProtocol,
            local_addr=("0.0.0.0", 0),
            allow_broadcast=True,
        )
    except OSError as err:
        raise TouchlineConnectionError(
            f"Could not open a UDP socket for Touchline discovery: {err}"
        ) from err

    try:
        transport.sendto(DISCOVERY_REQUEST, (broadcast_address, port))
        await asyncio.sleep(timeout)
    finally:
        transport.close()
    return list(protocol.controllers.values())
