"""Typed data models and enums for Roth Touchline controllers and rooms."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# Deadband the controller keeps around the setpoint before it toggles a zone's
# output, as found in the regulator firmware.
HEATING_HYSTERESIS = 0.19


class ControllerOperationMode(IntEnum):
    """Controller-wide operating mode applied via ``R0.OPModeRegler``."""

    DAY = 0
    NIGHT = 1
    OFF_HOLIDAY = 2


class RoomOperationMode(IntEnum):
    """Operating mode of an individual Touchline room thermostat (``G<n>.OPMode``)."""

    NORMAL = 0
    NIGHT = 1
    HOLIDAY = 2


class WeekProgram(IntEnum):
    """Active weekly schedule program of a room thermostat (``G<n>.WeekProg``)."""

    OFF = 0
    PRO_1 = 1
    PRO_2 = 2
    PRO_3 = 3


class TemperatureUnit(IntEnum):
    """Display temperature unit configured for a room thermostat (``G<n>.TempSIUnit``)."""

    CELSIUS = 0
    FAHRENHEIT = 1


class TouchlineErrorCode(IntEnum):
    """Active controller-level alarm code reported via ``R0.ErrorCode``."""

    NO_ERROR = 0
    HIGH_LIMIT_DEW_POINT = 1
    HIGH_LIMIT_SUPPLY_WATER = 2
    RF_COMMUNICATION_INTERRUPTED = 3


@dataclass(frozen=True)
class ControllerStatus:
    """Immutable snapshot of controller identity, network, firmware, and alarms."""

    unique_id: str | None
    controller_id: int | None
    paired_devices: int | None
    total_devices: int
    is_master: bool | None
    slave_controllers: int | None
    hostname: str | None
    mac_address: str | None
    ip_address: str | None
    stm_app_version: str | None
    stm_bootloader_version: str | None
    actuator_app_version: str | None
    actuator_bootloader_version: str | None
    operation_mode: ControllerOperationMode | int | None
    error_code: TouchlineErrorCode | int | None
    safety_tripped: bool | None
    dew_point_active: bool | None
    week_program_warning: bool | None
    system_status: int | None
    timestamp: int | None


@dataclass(frozen=True)
class RoomStatus:
    """Immutable snapshot of a single paired Roth Touchline room thermostat."""

    index: int
    device_id: int | None
    controller_id: int | None
    unique_id: str | None
    name: str | None
    temperature: float | None
    target_temperature: float | None
    min_temperature: float | None
    max_temperature: float | None
    temperature_step: float | None
    operation_mode: RoomOperationMode | int | None
    operation_mode_enabled: bool | None
    week_program: WeekProgram | int | None
    week_program_enabled: bool | None
    temperature_unit: TemperatureUnit | int | None

    @property
    def heating(self) -> bool | None:
        """Whether the room is calling for heat, reconstructed from the setpoint.

        The controller does not expose a per-room output state, so this mirrors
        its regulation: heat is demanded once the room drops ``HEATING_HYSTERESIS``
        below the setpoint and stops once it rises the same amount above it. Inside
        that deadband the output depends on the previous relay state, which a single
        snapshot cannot know, so ``None`` is returned there. ``None`` is also
        returned when the temperature or setpoint is unavailable.
        """
        if self.temperature is None or self.target_temperature is None:
            return None
        delta = self.target_temperature - self.temperature
        if delta > HEATING_HYSTERESIS:
            return True
        if delta < -HEATING_HYSTERESIS:
            return False
        return None


@dataclass(frozen=True)
class TouchlineState:
    """Immutable point-in-time snapshot of a Roth Touchline controller."""

    controller: ControllerStatus
    rooms: tuple[RoomStatus, ...]
