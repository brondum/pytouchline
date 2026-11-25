from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
import logging
from typing import Any
import xml.etree.ElementTree as ET

import httpx
from httpx import AsyncClient

from ._controller import TouchlineController
from ._discovery import DiscoveredController, discover_controllers
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
    MISSING_VALUES,
    PARSE_ERRORS as _PARSE_ERRORS,
    READ_PATH,
    TEMP_SCALE,
    WRITE_PATH,
    XML_HEADERS,
    TouchlineConnectionError,
    TouchlineError,
    TouchlineHTTPError,
    TouchlineResponseError,
    TouchlineTimeoutError,
    _TouchlineTransport,
    build_read_request,
    build_xml_item,
    matches_numeric_echo,
    matches_text_echo,
    parse_xml_items,
    scale_temperature,
)

__author__ = "brondum"

__all__ = [
    "ControllerOperationMode",
    "ControllerStatus",
    "DiscoveredController",
    "Parameter",
    "PyTouchline",
    "RoomOperationMode",
    "RoomStatus",
    "TemperatureUnit",
    "TouchlineConnectionError",
    "TouchlineController",
    "TouchlineError",
    "TouchlineErrorCode",
    "TouchlineHTTPError",
    "TouchlineResponseError",
    "TouchlineState",
    "TouchlineTimeoutError",
    "WeekProgram",
    "discover_controllers",
]

logger = logging.getLogger(__name__)


class PyTouchline(object):
    """
    A Python interface for controlling a Roth Touchline heat pump controller.

    Attributes:
            id (int): The ID of the sensor.
            url (str): The URL of the heat pump controller.
            timeout (float): HTTP request timeout in seconds (default: 10.0).
            client (httpx.AsyncClient | None): Optional shared client. It is not
                closed by this class. When omitted, a new client is created per request.
    """

    def __init__(
        self,
        id: int = 0,
        url: str = "",
        timeout: float = 10.0,
        client: AsyncClient | None = None,
    ) -> None:
        self._id = id
        self._url = url
        self._timeout = timeout
        self._client = client
        self._temp_scale = TEMP_SCALE
        self._header = dict(XML_HEADERS)
        self._read_path = READ_PATH
        self._write_path = WRITE_PATH
        self._transport = _TouchlineTransport(
            url=url,
            timeout=timeout,
            client=client,
            client_factory=lambda: self.get_async_client(),
            read_path=self._read_path,
            write_path=self._write_path,
            headers=self._header,
        )
        self._parameter: dict[str, str] = {}
        self.devices: list[Any] = []
        self._xml_element_list: list[Parameter] = [
            Parameter(name="name", desc="Name", type=Parameter.G),
            Parameter(name="SollTempMaxVal", desc="Setpoint max", type=Parameter.G),
            Parameter(name="SollTempMinVal", desc="Setpoint min", type=Parameter.G),
            Parameter(name="WeekProg", desc="Week program", type=Parameter.G),
            Parameter(name="OPMode", desc="Operation mode", type=Parameter.G),
            Parameter(name="SollTemp", desc="Setpoint", type=Parameter.G),
            Parameter(name="RaumTemp", desc="Temperature", type=Parameter.G),
            Parameter(name="kurzID", desc="Device ID", type=Parameter.G),
            Parameter(name="ownerKurzID", desc="Controller ID", type=Parameter.G),
        ]

    def _sync_transport(self) -> _TouchlineTransport:
        self._transport.url = self._url
        self._transport.timeout = self._timeout
        self._transport.client = self._client
        self._transport.read_path = self._read_path
        self._transport.write_path = self._write_path
        self._transport.headers = self._header
        return self._transport

    def get_async_client(self) -> AsyncClient:
        return httpx.AsyncClient(verify=False, timeout=self._timeout)

    @asynccontextmanager
    async def _async_client(self) -> AsyncIterator[AsyncClient]:
        async with self._sync_transport().async_client() as client:
            yield client

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return await self._sync_transport().request_async(method, url, **kwargs)

    async def get_number_of_devices_async(self) -> int:
        request = self._get_touchline_request([build_xml_item(["totalNumberOfDevices"])])
        response = await self._request_and_receive_xml(request)
        try:
            raw_count = self._parse_number_of_devices(response, "totalNumberOfDevices")
            if raw_count is None or raw_count in MISSING_VALUES:
                raise ValueError("Missing number of devices")
            return int(raw_count)
        except _PARSE_ERRORS as e:
            raise TouchlineResponseError("Could not fetch the number of devices") from e

    def get_number_of_devices(self) -> int:
        return asyncio.run(self.get_number_of_devices_async())

    async def get_hostname_async(self) -> str | None:
        request = self._get_touchline_request([build_xml_item(["hw.HostName"])])
        response = await self._request_and_receive_xml(request)
        try:
            hostname = self._parse_number_of_devices(response, "hw.HostName")
            return None if hostname in MISSING_VALUES else hostname
        except _PARSE_ERRORS as e:
            raise TouchlineResponseError("Could not fetch the hostname") from e

    def get_hostname(self) -> str | None:
        return asyncio.run(self.get_hostname_async())

    async def get_status_async(self) -> str | None:
        request = self._get_touchline_request([build_xml_item(["R0.SystemStatus"])])
        response = await self._request_and_receive_xml(request)
        try:
            status = self._parse_number_of_devices(response, "R0.SystemStatus")
            return None if status in MISSING_VALUES else status
        except _PARSE_ERRORS as e:
            raise TouchlineResponseError("Could not fetch the system status") from e

    def get_status(self) -> str | None:
        return asyncio.run(self.get_status_async())

    async def update_async(self) -> None:
        device_items = self._get_touchline_device_item(self._id)
        request = self._get_touchline_request(device_items)
        response = await self._request_and_receive_xml(request)
        try:
            self._parse_device(response)
        except _PARSE_ERRORS as e:
            raise TouchlineResponseError(f"Could not parse device {self._id}") from e

    def update(self) -> None:
        return asyncio.run(self.update_async())

    @staticmethod
    def _format_parameter_key(parameter: Parameter, device_id: int | str) -> str:
        param_type = parameter.get_type()
        if param_type == Parameter.G:
            return f"G{device_id}.{parameter.get_name()}"
        if param_type == Parameter.R:
            return f"R0.{parameter.get_name()}"
        return f"CD.{parameter.get_name()}"

    def _resolve_device_unique_id(self, items: Mapping[str, str | None]) -> str:
        expected_prefix = f"G{self._id}."
        if any(key.startswith(expected_prefix) for key in items):
            return str(self._id)
        for key in items:
            if key.startswith("G") and "." in key:
                room_id = key.split(".", 1)[0][1:]
                if room_id.isdigit():
                    return room_id
        raise ValueError(f"No parameters returned for device G{self._id}")

    def _parse_device(self, response: ET.Element) -> None:
        self.devices = []
        items = parse_xml_items(response)
        unique_id = self._resolve_device_unique_id(items)
        self._parameter["Unique ID"] = unique_id
        for parameter in self._xml_element_list:
            xml_key = self._format_parameter_key(parameter, unique_id)
            raw_value = items.get(xml_key)
            self._parameter[parameter.get_desc()] = (
                "NA" if raw_value in MISSING_VALUES else str(raw_value)
            )

    def _get_touchline_request(self, items: list[str]) -> str:
        return build_read_request(items)

    async def _write_raw_parameter_async(
        self,
        key: str,
        value: str | int | float,
        *,
        error_label: str | None = None,
    ) -> bytes:
        return await self._sync_transport().write_parameter_async(
            key, value, error_label=error_label
        )

    async def write_parameter_async(
        self, parameter: str, value: str | int | float
    ) -> bytes:
        unique_id = self._parameter.get("Unique ID", str(self._id))
        return await self._write_raw_parameter_async(
            f"G{unique_id}.{parameter}",
            value,
            error_label=parameter,
        )

    def write_parameter(self, parameter: str, value: str | int | float) -> bytes:
        return asyncio.run(self.write_parameter_async(parameter, value))

    async def _request_and_receive_xml(self, req_key: str) -> ET.Element:
        return await self._sync_transport().request_xml_async(req_key)

    def _parse_number_of_devices(
        self, response: ET.Element, key: str | None = None
    ) -> str | None:
        items = parse_xml_items(response)
        if key is not None:
            if key not in items:
                raise ValueError(f"Missing {key}")
            return items[key]
        if "totalNumberOfDevices" in items:
            return items["totalNumberOfDevices"]
        if items:
            return next(iter(items.values()))
        value = response.find("item_list/i/v")
        if value is None:
            raise ValueError("Missing value")
        return value.text

    def _get_touchline_device_item(self, id: int) -> list[str]:
        keys = [
            self._format_parameter_key(parameter, id)
            for parameter in self._xml_element_list
        ]
        return [build_xml_item(keys)]

    def _get_int_parameter(self, key: str) -> int | None:
        value = self._parameter.get(key)
        if value in MISSING_VALUES:
            return None
        assert value is not None
        try:
            return int(value)
        except ValueError as e:
            raise TouchlineResponseError(
                f"Invalid integer value for {key} on device {self._id}"
            ) from e

    def _get_scaled_temperature(self, key: str) -> float | None:
        raw = self._get_int_parameter(key)
        return None if raw is None else raw / self._temp_scale

    def get_name(self) -> str | None:
        value = self._parameter.get("Name")
        if value in MISSING_VALUES:
            return None
        return value

    async def set_name_async(self, value: str) -> bool:
        response = await self.write_parameter_async("name", value)
        return matches_text_echo(response, str(value))

    def set_name(self, value: str) -> bool:
        return asyncio.run(self.set_name_async(value))

    def get_current_temperature(self) -> float | None:
        return self._get_scaled_temperature("Temperature")

    def get_target_temperature(self) -> float | None:
        return self._get_scaled_temperature("Setpoint")

    async def set_target_temperature_async(self, value: float) -> bool:
        scaled = scale_temperature(value, self._temp_scale)
        response = await self.write_parameter_async("SollTemp", scaled)
        return matches_numeric_echo(response, scaled)

    def set_target_temperature(self, value: float) -> bool:
        return asyncio.run(self.set_target_temperature_async(value))

    def get_target_temperature_high(self) -> float | None:
        return self._get_scaled_temperature("Setpoint max")

    async def set_target_temperature_high_async(self, value: float) -> bool:
        scaled = scale_temperature(value, self._temp_scale)
        response = await self.write_parameter_async("SollTempMaxVal", scaled)
        return matches_numeric_echo(response, scaled)

    def set_target_temperature_high(self, value: float) -> bool:
        return asyncio.run(self.set_target_temperature_high_async(value))

    def get_target_temperature_low(self) -> float | None:
        return self._get_scaled_temperature("Setpoint min")

    async def set_target_temperature_low_async(self, value: float) -> bool:
        scaled = scale_temperature(value, self._temp_scale)
        response = await self.write_parameter_async("SollTempMinVal", scaled)
        return matches_numeric_echo(response, scaled)

    def set_target_temperature_low(self, value: float) -> bool:
        return asyncio.run(self.set_target_temperature_low_async(value))

    def get_week_program(self) -> int | None:
        return self._get_int_parameter("Week program")

    async def set_week_program_async(self, value: int) -> bool:
        target = int(value)
        response = await self.write_parameter_async("WeekProg", target)
        return matches_numeric_echo(response, target)

    def set_week_program(self, value: int) -> bool:
        return asyncio.run(self.set_week_program_async(value))

    def get_operation_mode(self) -> int | None:
        return self._get_int_parameter("Operation mode")

    async def set_operation_mode_async(self, value: int) -> bool:
        target = int(value)
        response = await self.write_parameter_async("OPMode", target)
        return matches_numeric_echo(response, target)

    def set_operation_mode(self, value: int) -> bool:
        return asyncio.run(self.set_operation_mode_async(value))

    def get_device_id(self) -> int | None:
        return self._get_int_parameter("Device ID")

    def get_controller_id(self) -> int | None:
        return self._get_int_parameter("Controller ID")


class Parameter(object):
    CD = 0
    G = 1
    R = 2

    def __init__(self, name: str, desc: str, type: int) -> None:
        self._name = name
        self._desc = desc
        self._type = type

    def get_name(self) -> str:
        return self._name

    def get_desc(self) -> str:
        return self._desc

    def get_type(self) -> int:
        return self._type
