import pytest
from pytouchline_extended import PyTouchline, Parameter
from unittest.mock import AsyncMock, patch, MagicMock
import xml.etree.ElementTree as ET


def test_init():
    touchline = PyTouchline(id=1, url="http://192.168.1.254")
    assert touchline._id == 1
    assert touchline._url == "http://192.168.1.254"
    assert touchline._temp_scale == 100
    assert touchline._read_path == "/cgi-bin/ILRReadValues.cgi"
    assert touchline._write_path == "/cgi-bin/writeVal.cgi"


def test_init_defaults():
    touchline = PyTouchline()
    assert touchline._id == 0
    assert touchline._url == ""


def test_get_touchline_request():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")
    items = ["<i><n>test</n></i>"]
    request = touchline._get_touchline_request(items)

    assert "<body>" in request
    assert "<version>1.0</version>" in request
    assert "<client>IMaster6_02_00</client>" in request
    assert "<client_ver>6.02.0006</client_ver>" in request
    assert "<file_name>room</file_name>" in request
    assert "<item_list>" in request
    assert "<i><n>test</n></i>" in request
    assert "</item_list>" in request
    assert "</body>" in request


def test_get_touchline_device_item():
    touchline = PyTouchline(id=5, url="http://192.168.1.254")
    items = touchline._get_touchline_device_item(5)

    assert len(items) == 1
    assert "<i>" in items[0]
    assert "</i>" in items[0]
    assert "<n>G5.name</n>" in items[0]
    assert "<n>G5.SollTemp</n>" in items[0]
    assert "<n>G5.RaumTemp</n>" in items[0]
    assert "<n>CD.upass</n>" in items[0]


def test_parse_number_of_devices():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")
    xml_response = ET.fromstring("""
        <body>
            <item_list>
                <i>
                    <n>totalNumberOfDevices</n>
                    <v>5</v>
                </i>
            </item_list>
        </body>
    """)

    result = touchline._parse_number_of_devices(xml_response)
    assert result == "5"


def test_parse_device():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")
    xml_response = ET.fromstring("""
        <body>
            <item_list>
                <i>
                    <n>G0.name</n>
                    <v>Living Room</v>
                    <n>CD.upass</n>
                    <v>password</v>
                    <n>G0.SollTempMaxVal</n>
                    <v>3000</v>
                    <n>G0.SollTempMinVal</n>
                    <v>500</v>
                    <n>G0.WeekProg</n>
                    <v>0</v>
                    <n>G0.OPMode</n>
                    <v>1</v>
                    <n>G0.SollTemp</n>
                    <v>2200</v>
                    <n>G0.RaumTemp</n>
                    <v>2150</v>
                    <n>G0.kurzID</n>
                    <v>1</v>
                    <n>G0.ownerKurzID</n>
                    <v>100</v>
                </i>
            </item_list>
        </body>
    """)

    touchline._parse_device(xml_response)
    assert touchline._parameter["Name"] == "Living Room"
    assert touchline._parameter["Temperature"] == "2150"
    assert touchline._parameter["Setpoint"] == "2200"
    assert touchline._parameter["Device ID"] == "1"
    assert touchline._parameter["Controller ID"] == "100"


def test_get_name():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    # Test when name doesn't exist
    assert touchline.get_name() is None

    # Test when name exists
    touchline._parameter["Name"] = "Kitchen"
    assert touchline.get_name() == "Kitchen"


def test_get_current_temperature():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    # Test when temperature doesn't exist
    assert touchline.get_current_temperature() is None

    # Test when temperature exists (2150 = 21.50°C)
    touchline._parameter["Temperature"] = "2150"
    assert touchline.get_current_temperature() == 21.5


def test_get_target_temperature():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    # Test when setpoint doesn't exist
    assert touchline.get_target_temperature() is None

    # Test when setpoint exists (2200 = 22.00°C)
    touchline._parameter["Setpoint"] = "2200"
    assert touchline.get_target_temperature() == 22.0


def test_get_target_temperature_high():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    assert touchline.get_target_temperature_high() is None

    touchline._parameter["Setpoint max"] = "3000"
    assert touchline.get_target_temperature_high() == 30.0


def test_get_target_temperature_low():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    assert touchline.get_target_temperature_low() is None

    touchline._parameter["Setpoint min"] = "500"
    assert touchline.get_target_temperature_low() == 5.0


def test_get_week_program():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    assert touchline.get_week_program() is None

    touchline._parameter["Week program"] = "2"
    assert touchline.get_week_program() == 2


def test_get_operation_mode():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    assert touchline.get_operation_mode() is None

    touchline._parameter["Operation mode"] = "1"
    assert touchline.get_operation_mode() == 1


def test_get_device_id():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    assert touchline.get_device_id() is None

    touchline._parameter["Device ID"] = "5"
    assert touchline.get_device_id() == 5


def test_get_controller_id():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    assert touchline.get_controller_id() is None

    touchline._parameter["Controller ID"] = "10"
    assert touchline.get_controller_id() == 10


def test_parameter_class():
    param = Parameter(name="test_name", desc="Test Description", type=Parameter.G)

    assert param.get_name() == "test_name"
    assert param.get_desc() == "Test Description"
    assert param.get_type() == Parameter.G
    assert param.get_type() == 1


def test_parameter_types():
    assert Parameter.CD == 0
    assert Parameter.G == 1
    assert Parameter.R == 2


@pytest.mark.asyncio
async def test_get_number_of_devices_async_success():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    mock_response = ET.fromstring("""
        <body>
            <item_list>
                <i>
                    <n>totalNumberOfDevices</n>
                    <v>3</v>
                </i>
            </item_list>
        </body>
    """)

    with patch.object(touchline, '_request_and_receive_xml', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response
        result = await touchline.get_number_of_devices_async()
        assert result == 3


@pytest.mark.asyncio
async def test_get_number_of_devices_async_failure():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    # Simulate a response where parsing fails (AttributeError from None)
    mock_response = ET.fromstring("""
        <body>
            <item_list>
            </item_list>
        </body>
    """)

    with patch.object(touchline, '_request_and_receive_xml', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response
        with pytest.raises(Exception):  # Will raise AttributeError which becomes Exception
            await touchline.get_number_of_devices_async()


@pytest.mark.asyncio
async def test_get_hostname_async():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    mock_response = ET.fromstring("""
        <body>
            <item_list>
                <i>
                    <n>hw.HostName</n>
                    <v>TouchlineController</v>
                </i>
            </item_list>
        </body>
    """)

    with patch.object(touchline, '_request_and_receive_xml', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response
        result = await touchline.get_hostname_async()
        assert result == "TouchlineController"


@pytest.mark.asyncio
async def test_update_async():
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    mock_response = ET.fromstring("""
        <body>
            <item_list>
                <i>
                    <n>G0.name</n>
                    <v>Bedroom</v>
                    <n>CD.upass</n>
                    <v>password</v>
                    <n>G0.SollTempMaxVal</n>
                    <v>3000</v>
                    <n>G0.SollTempMinVal</n>
                    <v>500</v>
                    <n>G0.WeekProg</n>
                    <v>0</v>
                    <n>G0.OPMode</n>
                    <v>1</v>
                    <n>G0.SollTemp</n>
                    <v>2100</v>
                    <n>G0.RaumTemp</n>
                    <v>2050</v>
                    <n>G0.kurzID</n>
                    <v>2</v>
                    <n>G0.ownerKurzID</n>
                    <v>100</v>
                </i>
            </item_list>
        </body>
    """)

    with patch.object(touchline, '_request_and_receive_xml', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response
        await touchline.update_async()

        assert touchline.get_name() == "Bedroom"
        assert touchline.get_current_temperature() == 20.5
        assert touchline.get_target_temperature() == 21.0


@pytest.mark.asyncio
async def test_request_and_receive_xml_empty_response():
    """Test that empty responses are handled gracefully"""
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.content = b""  # Empty response

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_response)

        with pytest.raises(Exception, match="Touchline controller returned empty response"):
            await touchline._request_and_receive_xml("<test/>")


@pytest.mark.asyncio
async def test_request_and_receive_xml_invalid_xml():
    """Test that invalid XML responses are handled gracefully"""
    touchline = PyTouchline(id=0, url="http://192.168.1.254")

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.content = b"This is not XML"

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_response)

        with pytest.raises(Exception, match="Invalid XML response from Touchline controller"):
            await touchline._request_and_receive_xml("<test/>")