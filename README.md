# Python Library for Roth Touchline (Extended)

This is an extended version of the original `pytouchline` library, a simple helper library for controlling a Roth Touchline heat pump controller. This fork introduces additional features and improvements over the original version.

## Installation

You can install the extended version of `pytouchline` from PyPI:

```bash
pip install pytouchline_extended
```

## Usage

Here's a basic example of how to use `pytouchline_extended`:

```python
from pytouchline_extended import PyTouchline

py_touchline = PyTouchline(url="http://192.168.1.254")

numberOfDevices = py_touchline.get_number_of_devices()
# for each device, get information
for x in range(0, numberOfDevices):
	devices.append(PyTouchline(id=x, url="http://192.168.1.254"))
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

For a more ex

## Contributing

Contributions to `pytouchline_extended` are welcome! You are welcome to create issues or pull requests.

## License

`pytouchline_extended` is licensed under the MIT License. See [LICENSE](LICENSE) for more information.
```