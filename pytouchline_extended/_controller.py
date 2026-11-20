"""Async-first serialized controller client for classic Roth Touchline units."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from enum import IntEnum
from typing import TypeVar

from httpx import AsyncClient

from ._models import (
    ControllerOperationMode,
    ControllerStatus,
    RoomOperationMode,
    RoomStatus,
    TemperatureUnit,
    TouchlineErrorCode,
    TouchlineState,
    WeekProgram,
)
from ._transport import (
    MAX_READ_BODY_BYTES,
    MISSING_VALUES,
    TEMP_SCALE,
    TouchlineResponseError,
    _TouchlineTransport,
    matches_numeric_echo,
    matches_text_echo,
    scale_temperature,
)

DEFAULT_TEMPERATURE_STEP = 0.5

CONTROLLER_PARAMETER_KEYS: tuple[str, ...] = (
    "totalNumberOfDevices",
    "isMaster",
    "numberOfSlaveControllers",
    "R0.uniqueID",
    "R0.kurzID",
    "R0.numberOfPairedDevices",
    "R0.OPModeRegler",
    "R0.ErrorCode",
    "R0.Safety",
    "R0.Taupunkt",
    "R0.WeekProgWarn",
    "R0.SystemStatus",
    "R0.DateTime",
    "hw.HostName",
    "hw.Addr",
    "hw.IP",
    "STM-APP",
    "STM-BL",
    "STELL-APP",
    "STELL-BL",
)

ROOM_PARAMETER_NAMES: tuple[str, ...] = (
    "name",
    "RaumTemp",
    "SollTemp",
    "SollTempMinVal",
    "SollTempMaxVal",
    "SollTempStepVal",
    "OPMode",
    "OPModeEna",
    "WeekProg",
    "WeekProgEna",
    "TempSIUnit",
    "kurzID",
    "ownerKurzID",
)

_EnumT = TypeVar("_EnumT", bound=IntEnum)


def _validate_room_index(room_index: int) -> int:
    """Validate that ``room_index`` is a non-negative integer slot index."""
    if isinstance(room_index, bool) or room_index < 0:
        raise ValueError("room_index must be a non-negative integer")
    return int(room_index)


def _validate_controller_mode(
    mode: ControllerOperationMode | int,
) -> ControllerOperationMode:
    """Validate ``mode`` as a supported ``ControllerOperationMode`` (0..2)."""
    if isinstance(mode, bool):
        raise ValueError("mode must be a ControllerOperationMode or int in 0..2")
    try:
        return ControllerOperationMode(int(mode))
    except (TypeError, ValueError) as err:
        raise ValueError(
            f"Unsupported controller operation mode {mode!r}; expected 0, 1, or 2"
        ) from err


def _parse_optional_str(items: Mapping[str, str | None], key: str) -> str | None:
    """Return a non-empty string parameter or ``None`` when missing/``NA``."""
    raw = items.get(key)
    if raw in MISSING_VALUES:
        return None
    return raw


def _parse_optional_int(items: Mapping[str, str | None], key: str) -> int | None:
    """Parse an integer parameter or return ``None`` when missing/``NA``."""
    raw = items.get(key)
    if raw in MISSING_VALUES:
        return None
    assert raw is not None
    try:
        return int(raw)
    except ValueError as err:
        raise TouchlineResponseError(
            f"Invalid integer value for {key}: {raw!r}"
        ) from err


def _parse_optional_bool(items: Mapping[str, str | None], key: str) -> bool | None:
    """Parse an integer ``0``/``1`` flag into ``bool`` or ``None`` when missing."""
    value = _parse_optional_int(items, key)
    return None if value is None else value != 0


def _parse_scaled_temp(items: Mapping[str, str | None], key: str) -> float | None:
    """Parse a temperature in hundredths of a degree into ``float`` Celsius."""
    raw = _parse_optional_int(items, key)
    return None if raw is None else raw / TEMP_SCALE


def _parse_temperature_step(items: Mapping[str, str | None], key: str) -> float | None:
    """Parse ``SollTempStepVal``, falling back to ``0.5 °C`` when firmware reports ``<= 0``."""
    raw = _parse_optional_int(items, key)
    if raw is None:
        return None
    if raw <= 0:
        return DEFAULT_TEMPERATURE_STEP
    return raw / TEMP_SCALE


def _parse_optional_enum(
    items: Mapping[str, str | None],
    key: str,
    enum_cls: type[_EnumT],
) -> _EnumT | int | None:
    """Convert known integers to ``enum_cls`` and preserve unknown firmware integers."""
    raw = _parse_optional_int(items, key)
    if raw is None:
        return None
    try:
        return enum_cls(raw)
    except ValueError:
        return raw


def _build_room_keys(room_index: int) -> list[str]:
    """Return the XML parameter keys for room ``G<room_index>``."""
    prefix = f"G{room_index}."
    return [f"{prefix}{name}" for name in ROOM_PARAMETER_NAMES]


def _parse_controller_status(items: Mapping[str, str | None]) -> ControllerStatus:
    """Construct an immutable ``ControllerStatus`` from merged XML key/value items."""
    total_devices = _parse_optional_int(items, "totalNumberOfDevices")
    if total_devices is None or total_devices < 0:
        raise TouchlineResponseError("Could not fetch totalNumberOfDevices")

    return ControllerStatus(
        unique_id=_parse_optional_str(items, "R0.uniqueID"),
        controller_id=_parse_optional_int(items, "R0.kurzID"),
        paired_devices=_parse_optional_int(items, "R0.numberOfPairedDevices"),
        total_devices=total_devices,
        is_master=_parse_optional_bool(items, "isMaster"),
        slave_controllers=_parse_optional_int(items, "numberOfSlaveControllers"),
        hostname=_parse_optional_str(items, "hw.HostName"),
        mac_address=_parse_optional_str(items, "hw.Addr"),
        ip_address=_parse_optional_str(items, "hw.IP"),
        stm_app_version=_parse_optional_str(items, "STM-APP"),
        stm_bootloader_version=_parse_optional_str(items, "STM-BL"),
        actuator_app_version=_parse_optional_str(items, "STELL-APP"),
        actuator_bootloader_version=_parse_optional_str(items, "STELL-BL"),
        operation_mode=_parse_optional_enum(
            items, "R0.OPModeRegler", ControllerOperationMode
        ),
        error_code=_parse_optional_enum(items, "R0.ErrorCode", TouchlineErrorCode),
        safety_tripped=_parse_optional_bool(items, "R0.Safety"),
        dew_point_active=_parse_optional_bool(items, "R0.Taupunkt"),
        week_program_warning=_parse_optional_bool(items, "R0.WeekProgWarn"),
        system_status=_parse_optional_int(items, "R0.SystemStatus"),
        timestamp=_parse_optional_int(items, "R0.DateTime"),
    )


def _parse_room_status(
    items: Mapping[str, str | None], room_index: int
) -> RoomStatus:
    """Construct an immutable ``RoomStatus`` from merged XML key/value items."""
    prefix = f"G{room_index}."
    if not any(key.startswith(prefix) for key in items):
        raise TouchlineResponseError(
            f"Missing parameters for room G{room_index} in Touchline response"
        )

    device_id = _parse_optional_int(items, f"{prefix}kurzID")
    controller_id = _parse_optional_int(items, f"{prefix}ownerKurzID")
    unique_id = (
        f"{controller_id}-{device_id}"
        if controller_id is not None and device_id is not None
        else None
    )

    return RoomStatus(
        index=room_index,
        device_id=device_id,
        controller_id=controller_id,
        unique_id=unique_id,
        name=_parse_optional_str(items, f"{prefix}name"),
        temperature=_parse_scaled_temp(items, f"{prefix}RaumTemp"),
        target_temperature=_parse_scaled_temp(items, f"{prefix}SollTemp"),
        min_temperature=_parse_scaled_temp(items, f"{prefix}SollTempMinVal"),
        max_temperature=_parse_scaled_temp(items, f"{prefix}SollTempMaxVal"),
        temperature_step=_parse_temperature_step(items, f"{prefix}SollTempStepVal"),
        operation_mode=_parse_optional_enum(
            items, f"{prefix}OPMode", RoomOperationMode
        ),
        operation_mode_enabled=_parse_optional_bool(items, f"{prefix}OPModeEna"),
        week_program=_parse_optional_enum(items, f"{prefix}WeekProg", WeekProgram),
        week_program_enabled=_parse_optional_bool(items, f"{prefix}WeekProgEna"),
        temperature_unit=_parse_optional_enum(
            items, f"{prefix}TempSIUnit", TemperatureUnit
        ),
    )


class TouchlineController:
    """Async-first client for polling and controlling one Roth Touchline controller.

    All HTTP reads and writes on a controller instance are serialized behind an
    internal ``asyncio.Lock``, and bulk XML reads are split into compact
    sequential POST payloads (< 500 bytes, <= 10 keys per ``<i>``) for
    ``Keil-EWEB/2.1`` request and 1 KiB CGI response-buffer compatibility.
    """

    def __init__(
        self,
        url: str,
        timeout: float = 10.0,
        client: AsyncClient | None = None,
    ) -> None:
        self._transport = _TouchlineTransport(url=url, timeout=timeout, client=client)
        self._lock = asyncio.Lock()

    @property
    def url(self) -> str:
        """Return the base URL of the Roth Touchline controller."""
        return self._transport.url

    @property
    def timeout(self) -> float:
        """Return the per-request HTTP timeout in seconds."""
        return self._transport.timeout

    async def _fetch_controller_status_unlocked(self) -> ControllerStatus:
        """Fetch and parse controller-level metadata while holding ``self._lock``."""
        items = await self._transport.read_chunked_items_async(
            [CONTROLLER_PARAMETER_KEYS],
            max_bytes=MAX_READ_BODY_BYTES,
        )
        return _parse_controller_status(items)

    async def fetch_async(self) -> TouchlineState:
        """Fetch controller metadata and all paired rooms in ``< 1,100``-byte XML chunks."""
        async with self._lock:
            controller = await self._fetch_controller_status_unlocked()
            if controller.total_devices == 0:
                return TouchlineState(controller=controller, rooms=())

            room_groups = [
                _build_room_keys(idx) for idx in range(controller.total_devices)
            ]
            room_items = await self._transport.read_chunked_items_async(
                room_groups,
                max_bytes=MAX_READ_BODY_BYTES,
            )
            rooms = tuple(
                _parse_room_status(room_items, idx)
                for idx in range(controller.total_devices)
            )
            return TouchlineState(controller=controller, rooms=rooms)

    async def _write_room_scaled_temp_async(
        self, room_index: int, parameter: str, temperature: float
    ) -> bool:
        idx = _validate_room_index(room_index)
        scaled = scale_temperature(temperature)
        async with self._lock:
            response = await self._transport.write_parameter_async(
                f"G{idx}.{parameter}",
                scaled,
                error_label=parameter,
            )
        return matches_numeric_echo(response, scaled)

    async def _write_room_int_async(
        self, room_index: int, parameter: str, value: int
    ) -> bool:
        idx = _validate_room_index(room_index)
        target = int(value)
        async with self._lock:
            response = await self._transport.write_parameter_async(
                f"G{idx}.{parameter}",
                target,
                error_label=parameter,
            )
        return matches_numeric_echo(response, target)

    async def set_room_target_temperature_async(
        self, room_index: int, temperature: float
    ) -> bool:
        """Set target room temperature (``G<n>.SollTemp``) in degrees Celsius."""
        return await self._write_room_scaled_temp_async(
            room_index, "SollTemp", temperature
        )

    async def set_room_min_temperature_async(
        self, room_index: int, temperature: float
    ) -> bool:
        """Set minimum allowed room setpoint (``G<n>.SollTempMinVal``) in Celsius."""
        return await self._write_room_scaled_temp_async(
            room_index, "SollTempMinVal", temperature
        )

    async def set_room_max_temperature_async(
        self, room_index: int, temperature: float
    ) -> bool:
        """Set maximum allowed room setpoint (``G<n>.SollTempMaxVal``) in Celsius."""
        return await self._write_room_scaled_temp_async(
            room_index, "SollTempMaxVal", temperature
        )

    async def set_room_operation_mode_async(
        self, room_index: int, mode: RoomOperationMode | int
    ) -> bool:
        """Set room operating mode (``G<n>.OPMode``: Normal=0, Night=1, Holiday=2)."""
        return await self._write_room_int_async(room_index, "OPMode", int(mode))

    async def set_room_week_program_async(
        self, room_index: int, program: WeekProgram | int
    ) -> bool:
        """Set active room weekly program (``G<n>.WeekProg``: Off=0, Pro 1..3=1..3)."""
        return await self._write_room_int_async(room_index, "WeekProg", int(program))

    async def set_room_name_async(self, room_index: int, name: str) -> bool:
        """Set room display name (``G<n>.name``)."""
        idx = _validate_room_index(room_index)
        async with self._lock:
            response = await self._transport.write_parameter_async(
                f"G{idx}.name",
                name,
                error_label="name",
            )
        return matches_text_echo(response, str(name))

    async def set_controller_operation_mode_async(
        self, mode: ControllerOperationMode | int
    ) -> bool:
        """Set controller-wide operating mode (``R0.OPModeRegler``: Day=0, Night=1, Off/Holiday=2).

        Active room weekly schedules (``Pro 1``–``Pro 3``) and subsequent local
        adjustments made directly on a room thermostat override this global mode.
        """
        target = int(_validate_controller_mode(mode))
        async with self._lock:
            response = await self._transport.write_parameter_async(
                "R0.OPModeRegler",
                target,
                error_label="R0.OPModeRegler",
            )
        return matches_numeric_echo(response, target)
