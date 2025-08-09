from pytouchline_extended import PyTouchline
import asyncio

async def main():
	URL = "http://192.168.10.162"

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
	
	await devices[4].set_target_temperature_async(22)

if __name__ == "__main__":
	asyncio.run(main())
