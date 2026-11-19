# Python Library for Roth Touchline (Extended)

This is an extended version of the original `pytouchline` library, a simple helper library for controlling a Roth Touchline heat pump controller. This fork introduces additional features and improvements over the original version.

## Installation

You can install the extended version of `pytouchline` from PyPI:

```bash
pip install pytouchline_extended
```

## Usage

### `TouchlineController` (Recommended Async API)

`TouchlineController` represents a single physical Roth Touchline controller. It serializes all reads and writes behind an internal `asyncio.Lock`, polls paired rooms in sequential `< 1,100`-byte XML chunks (preventing `Keil-EWEB/2.1` multi-segment POST hangs and socket-table exhaustion), and returns immutable `@dataclass` snapshots:

```python
import asyncio
import httpx

from pytouchline_extended import (
    RoomOperationMode,
    TouchlineController,
    TouchlineErrorCode,
    WeekProgram,
)


async def main() -> None:
    url = "http://192.168.1.254"

    async with httpx.AsyncClient(verify=False) as client:
        controller = TouchlineController(url=url, timeout=10.0, client=client)
        state = await controller.fetch_async()

        print(
            f"Controller {state.controller.hostname} "
            f"(serial={state.controller.unique_id}, mac={state.controller.mac_address}, "
            f"error={state.controller.error_code})"
        )
        if state.controller.error_code == TouchlineErrorCode.RF_COMMUNICATION_INTERRUPTED:
            print("Warning: RF link interrupted — check room thermostat batteries!")

        for room in state.rooms:
            print(
                f"[{room.index}] {room.name} ({room.unique_id}): "
                f"{room.temperature}°C -> {room.target_temperature}°C "
                f"(mode={room.operation_mode}, program={room.week_program})"
            )

        if state.rooms:
            await controller.set_room_target_temperature_async(0, 22.5)
            await controller.set_room_min_temperature_async(0, 5.0)
            await controller.set_room_max_temperature_async(0, 30.0)
            await controller.set_room_operation_mode_async(0, RoomOperationMode.NORMAL)
            await controller.set_room_week_program_async(0, WeekProgram.OFF)
            await controller.set_room_name_async(0, "Hovedsoverom")


if __name__ == "__main__":
    asyncio.run(main())
```

### Legacy Per-Room API (`PyTouchline`)

`PyTouchline` remains fully supported for backwards compatibility:

```python
from pytouchline_extended import PyTouchline

URL = "http://192.168.1.254"

py_touchline = PyTouchline(url=URL)

numberOfDevices = py_touchline.get_number_of_devices()
devices: list[PyTouchline] = []
# for each device, get information
for x in range(0, numberOfDevices):
	devices.append(PyTouchline(id=x, url=URL))
	devices[x].update()
	print(x)
	print(devices[x].get_name())
	print(devices[x].get_current_temperature())
	print(devices[x].get_target_temperature())
	print(devices[x].get_target_temperature_high())
	print(devices[x].get_target_temperature_low())
	print(devices[x].get_week_program())
	print(devices[x].get_operation_mode())
	print(devices[x].get_device_id())
	print(devices[x].get_controller_id())
	print(devices[x].get_hostname())
	print("-------------------------------------")

# set some values
print(devices[0].set_name("Hovedsoverom"))
print(devices[0].set_target_temperature(22.5))
print(devices[0].set_target_temperature_high(30))
print(devices[0].set_target_temperature_low(5))
print(devices[0].set_week_program(0))
print(devices[0].set_operation_mode(0))
```

### Asynchronous Example

```python
from pytouchline_extended import PyTouchline
import asyncio

async def main():
	URL = "http://192.168.1.254"

	py_touchline = PyTouchline(url=URL)

	numberOfDevices = await py_touchline.get_number_of_devices_async()
	devices: list[PyTouchline] = []
	# for each device, get information
	for x in range(0, numberOfDevices):
		devices.append(PyTouchline(id=x, url=URL))
		await devices[x].update_async()
		print(x)
		print(devices[x].get_name())
		print(devices[x].get_current_temperature())
		print(devices[x].get_target_temperature())
		print(devices[x].get_target_temperature_high())
		print(devices[x].get_target_temperature_low())
		print(devices[x].get_week_program())
		print(devices[x].get_operation_mode())
		print(devices[x].get_device_id())
		print(devices[x].get_controller_id())
		print("-------------------------------------")
	
	if len(devices) > 0:
		print(f"Hostname: {await devices[0].get_hostname_async()}")

		print(await devices[0].set_name_async("Hovedsoverom"))
		print(await devices[0].set_target_temperature_async(22.5))
		print(await devices[0].set_target_temperature_high_async(30))
		print(await devices[0].set_target_temperature_low_async(5))
		print(await devices[0].set_week_program_async(0))
		print(await devices[0].set_operation_mode_async(0))

if __name__ == "__main__":
	asyncio.run(main())
```

### Sharing an HTTP client

By default a new `httpx.AsyncClient` is created for every request. To reuse an
existing client, pass it to the constructor. The library never closes a client
it was given, and the `timeout` is still applied per request.

```python
async with httpx.AsyncClient() as client:
	py_touchline = PyTouchline(url=URL, client=client)
	numberOfDevices = await py_touchline.get_number_of_devices_async()
```

### Error handling

All errors raised by the library derive from `TouchlineError`:

| Exception | Raised when |
|-----------|-------------|
| `TouchlineConnectionError` | The controller cannot be reached |
| `TouchlineTimeoutError` | A request times out (subclass of `TouchlineConnectionError`) |
| `TouchlineHTTPError` | The controller responds with a non-success HTTP status (available as `status_code`) |
| `TouchlineResponseError` | The controller returns an empty, invalid or unexpected response |

The library does not log errors it raises; logging them is left to the caller.
Previous versions raised plain `Exception`; the new exceptions still derive from it.

```python
from pytouchline_extended import PyTouchline, TouchlineConnectionError, TouchlineError

try:
	await py_touchline.update_async()
except TouchlineConnectionError:
	print("Controller unreachable")
except TouchlineError:
	print("Unexpected response from controller")
```

## Protocol & Hardware Notes

Community-documented details on the classic Roth Touchline CGI/XML protocol, embedded `Keil-EWEB/2.1` HTTP server limits (`< 1,100`-byte POST chunking and single-connection serialization), parameter keys, and hardware limitations are available in [docs/PROTOCOL.md](./docs/PROTOCOL.md).

> **Note:** Those protocol notes were reverse-engineered from a personal controller for interoperability and may differ across hardware revisions, OEM variants, and firmware versions.

## Contributing

Contributions to `pytouchline_extended` are welcome! You are welcome to create issues or pull requests.

## License

`pytouchline_extended` is licensed under the MIT License. See [LICENSE](LICENSE) for more information.
```
