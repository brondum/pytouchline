from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from urllib.parse import unquote
import xml.etree.ElementTree as ET

import httpx
import pytest

from pytouchline_extended import (
    ControllerStatus,
    RoomOperationMode,
    RoomStatus,
    TemperatureUnit,
    TouchlineController,
    TouchlineErrorCode,
    TouchlineHTTPError,
    TouchlineResponseError,
    TouchlineState,
    WeekProgram,
)
from pytouchline_extended._transport import (
    MAX_READ_BODY_BYTES,
    build_chunked_read_requests,
)


def _extract_requested_keys(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    return [
        elem.text
        for elem in root.findall("item_list/i/n")
        if elem.text is not None
    ]


def _build_xml_response(values: dict[str, str | None], keys: list[str]) -> bytes:
    pairs = []
    for key in keys:
        if key not in values:
            continue
        val = values[key]
        if val is None:
            pairs.append(f"<n>{key}</n><v/>")
        else:
            pairs.append(f"<n>{key}</n><v>{val}</v>")
    body = (
        "<body>"
        "<version>1.0</version>"
        "<item_list_size>1</item_list_size>"
        f"<item_list><i>{''.join(pairs)}</i></item_list>"
        "</body>"
    )
    return body.encode("utf-8")


def _sample_room_values(room_count: int) -> dict[str, str | None]:
    data: dict[str, str | None] = {
        "totalNumberOfDevices": str(room_count),
        "isMaster": "1",
        "numberOfSlaveControllers": "0",
        "R0.uniqueID": "0123456789ABCDEF01234567",
        "R0.kurzID": "38",
        "R0.numberOfPairedDevices": str(room_count),
        "R0.ErrorCode": "0",
        "R0.Safety": "0",
        "R0.Taupunkt": "0",
        "R0.WeekProgWarn": "0",
        "R0.SystemStatus": "0",
        "R0.DateTime": "1732000000",
        "hw.HostName": "ROTH-000000",
        "hw.Addr": "00-11-22-33-44-55",
        "hw.IP": "192.168.1.50",
        "STM-APP": "A.FA",
        "STM-BL": "1.20",
        "STELL-APP": "1.42",
        "STELL-BL": "1.20",
    }
    for idx in range(room_count):
        prefix = f"G{idx}."
        data.update(
            {
                f"{prefix}name": f"Room {idx}",
                f"{prefix}RaumTemp": str(2000 + idx * 37),
                f"{prefix}SollTemp": str(2100 + idx * 50),
                f"{prefix}SollTempMinVal": "500",
                f"{prefix}SollTempMaxVal": "3000",
                f"{prefix}SollTempStepVal": "0",
                f"{prefix}OPMode": str(idx % 3),
                f"{prefix}OPModeEna": "1",
                f"{prefix}WeekProg": str(idx % 4),
                f"{prefix}WeekProgEna": "1" if idx % 2 == 0 else "0",
                f"{prefix}TempSIUnit": "0",
                f"{prefix}kurzID": str(10 + idx),
                f"{prefix}ownerKurzID": "38",
            }
        )
    return data


def test_build_chunked_read_requests_splits_oversized_group_and_rejects_huge_key():
    keys = [f"G0.CustomFieldNumber{i:02d}" for i in range(50)]
    chunks = build_chunked_read_requests([keys])
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) < MAX_READ_BODY_BYTES

    recovered: list[str] = []
    for chunk in chunks:
        recovered.extend(_extract_requested_keys(chunk.encode("utf-8")))
    assert recovered == keys

    with pytest.raises(ValueError, match="exceeds max request size"):
        build_chunked_read_requests([["x" * MAX_READ_BODY_BYTES]])


@pytest.mark.asyncio
@pytest.mark.parametrize("room_count", [0, 3, 7, 12])
async def test_fetch_async_chunks_under_1100_bytes(room_count: int):
    values = _sample_room_values(room_count)
    seen_payloads: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://192.168.1.50/cgi-bin/ILRReadValues.cgi"
        seen_payloads.append(request.content)
        assert len(request.content) < MAX_READ_BODY_BYTES
        assert b"CD.upass" not in request.content
        keys = _extract_requested_keys(request.content)
        return httpx.Response(200, content=_build_xml_response(values, keys))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = TouchlineController(
            url="http://192.168.1.50", timeout=5.0, client=client
        )
        assert controller.url == "http://192.168.1.50"
        assert controller.timeout == 5.0
        state = await controller.fetch_async()

    assert isinstance(state, TouchlineState)
    assert state.controller == ControllerStatus(
        unique_id="0123456789ABCDEF01234567",
        controller_id=38,
        paired_devices=room_count,
        total_devices=room_count,
        is_master=True,
        slave_controllers=0,
        hostname="ROTH-000000",
        mac_address="00-11-22-33-44-55",
        ip_address="192.168.1.50",
        stm_app_version="A.FA",
        stm_bootloader_version="1.20",
        actuator_app_version="1.42",
        actuator_bootloader_version="1.20",
        error_code=TouchlineErrorCode.NO_ERROR,
        safety_tripped=False,
        dew_point_active=False,
        week_program_warning=False,
        system_status=0,
        timestamp=1732000000,
    )
    assert len(state.rooms) == room_count

    with pytest.raises(FrozenInstanceError):
        state.controller.hostname = "Mutated"  # type: ignore[misc]

    if room_count == 0:
        assert len(seen_payloads) == 1
        assert state.rooms == ()
        return

    # 3 rooms fit per <1,100-byte chunk (971 bytes), plus 1 initial count request
    expected_room_chunks = (room_count + 2) // 3
    assert len(seen_payloads) == 1 + expected_room_chunks

    first = state.rooms[0]
    assert first == RoomStatus(
        index=0,
        device_id=10,
        controller_id=38,
        unique_id="38-10",
        name="Room 0",
        temperature=20.0,
        target_temperature=21.0,
        min_temperature=5.0,
        max_temperature=30.0,
        temperature_step=0.5,
        operation_mode=RoomOperationMode.NORMAL,
        operation_mode_enabled=True,
        week_program=WeekProgram.OFF,
        week_program_enabled=True,
        temperature_unit=TemperatureUnit.CELSIUS,
    )

    with pytest.raises(FrozenInstanceError):
        first.name = "Mutated"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_fetch_and_writes_are_serialized_by_controller_lock():
    values = _sample_room_values(7)
    in_flight = 0
    max_in_flight = 0
    events: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        is_write = "writeVal.cgi" in str(request.url)
        events.append("write" if is_write else "read")
        await asyncio.sleep(0.005)
        try:
            if is_write:
                return httpx.Response(200, content=b"2250")
            keys = _extract_requested_keys(request.content)
            return httpx.Response(200, content=_build_xml_response(values, keys))
        finally:
            in_flight -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        results = await asyncio.gather(
            controller.fetch_async(),
            controller.set_room_target_temperature_async(0, 22.5),
            controller.fetch_async(),
        )

    assert max_in_flight == 1
    assert isinstance(results[0], TouchlineState)
    assert results[1] is True
    assert isinstance(results[2], TouchlineState)
    # Each 7-room fetch is 4 contiguous "read" requests; "write" must never split a 4-read block
    write_idx = events.index("write")
    assert write_idx in (0, 4, 8)


@pytest.mark.asyncio
async def test_room_parsing_edge_cases_unknown_enums_step_and_latin1():
    def handler(request: httpx.Request) -> httpx.Response:
        keys = _extract_requested_keys(request.content)
        if "totalNumberOfDevices" in keys:
            return httpx.Response(
                200,
                content=_build_xml_response({"totalNumberOfDevices": "2"}, keys),
            )
        raw_xml = (
            "<body><item_list>"
            "<i>"
            "<n>G0.name</n><v>Børneværelse</v>"
            "<n>G0.RaumTemp</n><v>2267</v>"
            "<n>G0.SollTemp</n><v>2250</v>"
            "<n>G0.SollTempMinVal</n><v>600</v>"
            "<n>G0.SollTempMaxVal</n><v>2800</v>"
            "<n>G0.SollTempStepVal</n><v>100</v>"
            "<n>G0.OPMode</n><v>9</v>"
            "<n>G0.OPModeEna</n><v>0</v>"
            "<n>G0.WeekProg</n><v>7</v>"
            "<n>G0.WeekProgEna</n><v>1</v>"
            "<n>G0.TempSIUnit</n><v>1</v>"
            "<n>G0.kurzID</n><v>4</v>"
            "<n>G0.ownerKurzID</n><v>38</v>"
            "</i>"
            "<i>"
            "<n>G1.name</n><v>NA</v>"
            "<n>G1.RaumTemp</n><v></v>"
            "<n>G1.SollTempStepVal</n><v>NA</v>"
            "<n>G1.kurzID</n><v>5</v>"
            "</i>"
            "</item_list></body>"
        ).encode("cp1252")
        return httpx.Response(200, content=raw_xml)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        state = await controller.fetch_async()

    room0, room1 = state.rooms
    assert room0.name == "Børneværelse"
    assert room0.temperature == 22.67
    assert room0.target_temperature == 22.5
    assert room0.temperature_step == 1.0
    assert room0.operation_mode == 9
    assert not isinstance(room0.operation_mode, RoomOperationMode)
    assert room0.operation_mode_enabled is False
    assert room0.week_program == 7
    assert not isinstance(room0.week_program, WeekProgram)
    assert room0.week_program_enabled is True
    assert room0.temperature_unit is TemperatureUnit.FAHRENHEIT
    assert room0.unique_id == "38-4"

    assert room1.index == 1
    assert room1.device_id == 5
    assert room1.controller_id is None
    assert room1.unique_id is None
    assert room1.name is None
    assert room1.temperature is None
    assert room1.temperature_step is None
    assert room1.operation_mode is None
    assert room1.week_program is None
    assert room1.temperature_unit is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count_val",
    [None, "NA", "", "-1", "abc"],
)
async def test_fetch_async_invalid_device_count_raises(count_val: str | None):
    def handler(request: httpx.Request) -> httpx.Response:
        keys = _extract_requested_keys(request.content)
        values = {} if count_val is None else {"totalNumberOfDevices": count_val}
        return httpx.Response(200, content=_build_xml_response(values, keys))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        with pytest.raises(TouchlineResponseError):
            await controller.fetch_async()


@pytest.mark.asyncio
async def test_fetch_async_missing_room_or_corrupt_int_raises():
    # Missing G0 parameters completely
    def missing_room_handler(request: httpx.Request) -> httpx.Response:
        keys = _extract_requested_keys(request.content)
        if "totalNumberOfDevices" in keys:
            return httpx.Response(
                200, content=_build_xml_response({"totalNumberOfDevices": "1"}, keys)
            )
        return httpx.Response(
            200,
            content=b"<body><item_list><i><n>R0.SystemStatus</n><v>0</v></i></item_list></body>",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(missing_room_handler)
    ) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        with pytest.raises(TouchlineResponseError, match="Missing parameters for room G0"):
            await controller.fetch_async()

    # Corrupt integer in G0.RaumTemp
    def corrupt_int_handler(request: httpx.Request) -> httpx.Response:
        keys = _extract_requested_keys(request.content)
        if "totalNumberOfDevices" in keys:
            return httpx.Response(
                200, content=_build_xml_response({"totalNumberOfDevices": "1"}, keys)
            )
        return httpx.Response(
            200,
            content=b"<body><item_list><i><n>G0.RaumTemp</n><v>not_an_int</v></i></item_list></body>",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(corrupt_int_handler)
    ) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        with pytest.raises(TouchlineResponseError, match="Invalid integer value for G0.RaumTemp"):
            await controller.fetch_async()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_error_code", "expected_error_code"),
    [
        ("0", TouchlineErrorCode.NO_ERROR),
        ("1", TouchlineErrorCode.HIGH_LIMIT_DEW_POINT),
        ("2", TouchlineErrorCode.HIGH_LIMIT_SUPPLY_WATER),
        ("3", TouchlineErrorCode.RF_COMMUNICATION_INTERRUPTED),
        ("42", 42),
    ],
)
async def test_controller_status_alarms_empty_firmware_and_unknown_error_code(
    raw_error_code: str,
    expected_error_code: TouchlineErrorCode | int,
):
    values: dict[str, str | None] = {
        "totalNumberOfDevices": "0",
        "isMaster": "0",
        "numberOfSlaveControllers": "2",
        "R0.uniqueID": "ABCDEF0123456789ABCDEF01",
        "R0.kurzID": "109",
        "R0.numberOfPairedDevices": "4",
        "R0.ErrorCode": raw_error_code,
        "R0.Safety": "1",
        "R0.Taupunkt": "1",
        "R0.WeekProgWarn": "1",
        "R0.SystemStatus": "7",
        "R0.DateTime": "1732050000",
        "hw.HostName": "",
        "hw.Addr": "NA",
        "STM-APP": "",
        "STM-BL": "",
        "STELL-APP": "NA",
        "STELL-BL": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert len(request.content) < MAX_READ_BODY_BYTES
        keys = _extract_requested_keys(request.content)
        return httpx.Response(200, content=_build_xml_response(values, keys))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        state = await controller.fetch_async()

    ctrl = state.controller
    assert ctrl.unique_id == "ABCDEF0123456789ABCDEF01"
    assert ctrl.controller_id == 109
    assert ctrl.paired_devices == 4
    assert ctrl.total_devices == 0
    assert ctrl.is_master is False
    assert ctrl.slave_controllers == 2
    assert ctrl.hostname is None
    assert ctrl.mac_address is None
    assert ctrl.ip_address is None
    assert ctrl.stm_app_version is None
    assert ctrl.stm_bootloader_version is None
    assert ctrl.actuator_app_version is None
    assert ctrl.actuator_bootloader_version is None
    assert ctrl.error_code == expected_error_code
    if raw_error_code == "42":
        assert not isinstance(ctrl.error_code, TouchlineErrorCode)
    else:
        assert isinstance(ctrl.error_code, TouchlineErrorCode)
    assert ctrl.safety_tripped is True
    assert ctrl.dew_point_active is True
    assert ctrl.week_program_warning is True
    assert ctrl.system_status == 7
    assert ctrl.timestamp == 1732050000


@pytest.mark.asyncio
async def test_controller_status_corrupt_error_code_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        keys = _extract_requested_keys(request.content)
        values = {"totalNumberOfDevices": "0", "R0.ErrorCode": "bad_code"}
        return httpx.Response(200, content=_build_xml_response(values, keys))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        with pytest.raises(
            TouchlineResponseError, match="Invalid integer value for R0.ErrorCode"
        ):
            await controller.fetch_async()


@pytest.mark.asyncio
async def test_room_write_methods_and_validation():
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        query = request.url.raw_path.decode("ascii").split("?", 1)[1]
        key, raw_val = query.split("=", 1)
        if key == "G0.SollTemp":
            # Echo float format seen on some SpiderControl builds
            return httpx.Response(200, content=f"{raw_val}.0\r\n".encode("ascii"))
        return httpx.Response(200, content=unquote(raw_val).encode("utf-8"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)

        assert await controller.set_room_target_temperature_async(0, 22.5) is True
        assert await controller.set_room_min_temperature_async(1, 5.0) is True
        assert await controller.set_room_max_temperature_async(1, 30.0) is True
        assert (
            await controller.set_room_operation_mode_async(
                2, RoomOperationMode.HOLIDAY
            )
            is True
        )
        assert (
            await controller.set_room_week_program_async(2, WeekProgram.PRO_3) is True
        )
        assert await controller.set_room_name_async(3, "Living Room") is True

        for invalid_idx in (-1, True, False):
            with pytest.raises(ValueError, match="non-negative integer"):
                await controller.set_room_target_temperature_async(
                    invalid_idx, 21.0
                )

    assert seen_urls == [
        "http://192.168.1.50/cgi-bin/writeVal.cgi?G0.SollTemp=2250",
        "http://192.168.1.50/cgi-bin/writeVal.cgi?G1.SollTempMinVal=500",
        "http://192.168.1.50/cgi-bin/writeVal.cgi?G1.SollTempMaxVal=3000",
        "http://192.168.1.50/cgi-bin/writeVal.cgi?G2.OPMode=2",
        "http://192.168.1.50/cgi-bin/writeVal.cgi?G2.WeekProg=3",
        "http://192.168.1.50/cgi-bin/writeVal.cgi?G3.name=Living%20Room",
    ]


@pytest.mark.asyncio
async def test_room_write_mismatched_echo_and_http_error():
    def mismatch_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"9999")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(mismatch_handler)
    ) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        assert await controller.set_room_target_temperature_async(0, 21.0) is False
        assert await controller.set_room_name_async(0, "Office") is False

    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"Busy")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(error_handler)
    ) as client:
        controller = TouchlineController(url="http://192.168.1.50", client=client)
        with pytest.raises(TouchlineHTTPError) as exc_info:
            await controller.set_room_operation_mode_async(0, RoomOperationMode.NIGHT)
        assert exc_info.value.status_code == 503
