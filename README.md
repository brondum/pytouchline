# Python Library for Roth Touchline

A simple helper library for controlling a Roth Touchline heat pump controller

```py

from pytouchline_extended import PyTouchline

py_touchline = PyTouchline(ip_address="http://192.168.1.254")

numberOfDevices = py_touchline.get_number_of_devices()
device1 = PyTouchline(id=1)
device1.update()
print(device1.get_name())
print(device1.get_current_temperature())
print(device1.get_target_temperature())
```