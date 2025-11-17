import httpx
import cchardet as chardet
import xml.etree.ElementTree as ET
import asyncio
import logging

__author__ = 'brondum'

logger = logging.getLogger(__name__)


class PyTouchline(object):
	"""
	A Python interface for controlling a Roth Touchline heat pump controller.

	Attributes:
			id (int): The ID of the sensor.
			url (str): The URL of the heat pump controller.
			timeout (float): HTTP request timeout in seconds (default: 10.0).
	"""

	def __init__(self, id=0, url="", timeout=10.0):
		self._id = id
		self._url = url
		self._timeout = timeout
		self._temp_scale = 100
		self._header = {"Content-Type": "text/xml"}
		self._read_path = "/cgi-bin/ILRReadValues.cgi"
		self._write_path = "/cgi-bin/writeVal.cgi"
		self._parameter: dict[str, str] = {}
		self._xml_element_list: list[Parameter] = []
		self._xml_element_list.append(
			Parameter(name="name", desc="Name", type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="upass", desc="Password", type=Parameter.CD))
		self._xml_element_list.append(
			Parameter(name="SollTempMaxVal", desc="Setpoint max",
					  type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="SollTempMinVal", desc="Setpoint min",
					  type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="WeekProg", desc="Week program", type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="OPMode", desc="Operation mode", type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="SollTemp", desc="Setpoint", type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="RaumTemp", desc="Temperature", type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="kurzID", desc="Device ID", type=Parameter.G))
		self._xml_element_list.append(
			Parameter(name="ownerKurzID", desc="Controller ID",
					  type=Parameter.G))

	async def get_number_of_devices_async(self) -> int:
		number_of_devices_items = []
		number_of_devices_items.append("<i><n>totalNumberOfDevices</n></i>")
		request = self._get_touchline_request(number_of_devices_items)
		response = await self._request_and_receive_xml(request)
		number_of_devcies = self._parse_number_of_devices(response)
		if number_of_devcies is None:
			raise Exception("Could not fetch the number of devices")
		return int(number_of_devcies)

	def get_number_of_devices(self) -> int:
		return asyncio.run(self.get_number_of_devices_async())
	
	async def get_hostname_async(self) -> str | None:
		hostname_items = []
		hostname_items.append("<i><n>hw.HostName</n></i>")
		request = self._get_touchline_request(hostname_items)
		response = await self._request_and_receive_xml(request)
		return self._parse_number_of_devices(response)

	def get_hostname(self) -> str | None:
		return asyncio.run(self.get_hostname_async())

	async def get_status_async(self) -> str | None:
		status_items = []
		status_items.append("<i><n>R0.SystemStatus</n></i>")
		request = self._get_touchline_request(status_items)
		response = await self._request_and_receive_xml(request)
		return self._parse_number_of_devices(response)

	def get_status(self) -> str | None:
		return asyncio.run(self.get_status_async())

	# update the roth touchline device, and parse desc, id etc.
	async def update_async(self) -> None:
		device_items = self._get_touchline_device_item(self._id)
		request = self._get_touchline_request(device_items)
		response = await self._request_and_receive_xml(request)
		return self._parse_device(response)

	# update the roth touchline device, and parse desc, id etc.
	def update(self) -> None:
		return asyncio.run(self.update_async())

	def _parse_device(self, response):
		self.devices = []
		item_list = response.find('item_list')
		for item in item_list.iterfind("i"):
			list_iterator = 0
			device_list = list(item)
			for parameter in self._xml_element_list:
				if device_list[list_iterator].tag != "n":
					list_iterator -= 1
					self._parameter[parameter.get_desc()] = "NA"
				else:
					self._parameter[parameter.get_desc()] = str(
						device_list[list_iterator + 1].text)
					if list_iterator == 0:
						unique_id = device_list[list_iterator].text.split(".")[0].split("G")[1]
						self._parameter["Unique ID"] = unique_id
				list_iterator += 2

	def _get_touchline_request(self, items):
		request = "<body>"
		request += "<version>1.0</version>"
		request += "<client>IMaster6_02_00</client>"
		request += "<client_ver>6.02.0006</client_ver>"
		request += "<file_name>room</file_name>"
		request += "<item_list_size>0</item_list_size>"
		request += "<item_list>"
		for item in items:
			request += item
		request += "</item_list>"
		request += "</body>"
		return request

	async def write_parameter_async(self, parameter, value):
		async with httpx.AsyncClient(timeout=10.0) as client:
			response = await client.request(
				url=self._url +
					self._write_path + "?" +
					"G" + str(self._parameter["Unique ID"]) +
					"." + str(parameter) + "=" + str(value),
				method="GET",
			)

		if not response.is_success:
			logger.error("Failed to write parameter %s: HTTP %s - %s",
						 parameter, response.status_code, response.text)
			raise Exception("Failed to write parameter: Roth Touchline did not respond successfully")

		return response.content

	def write_parameter(self, parameter, value):
		return asyncio.run(self.write_parameter_async(parameter, value))

	async def _request_and_receive_xml(self, req_key):
		logger.debug("Requesting URL: %s%s (timeout: %.1fs)", self._url, self._read_path, self._timeout)

		try:
			async with httpx.AsyncClient(timeout=self._timeout) as client:
				response = await client.request(
					url=self._url + self._read_path,
					method="POST",
					data=req_key,
					headers=self._header
				)
		except httpx.TimeoutException as e:
			logger.error("Timeout (%.1fs) while connecting to Touchline controller at %s: %s",
						 self._timeout, self._url, str(e))
			raise Exception(f"Touchline controller timeout after {self._timeout} seconds: {e}")
		except httpx.RequestError as e:
			logger.error("Network error while connecting to Touchline controller at %s: %s", self._url, str(e))
			raise Exception(f"Network error connecting to Touchline controller: {e}")

		logger.debug("Response status: %s, content length: %d bytes",
					 response.status_code, len(response.content) if response.content else 0)

		if not response.is_success:
			logger.error("Failed to read from Touchline: HTTP %s - %s",
						 response.status_code, response.text)
			raise Exception("Roth Touchline did not respond successfully")

		content = response.content
		if not content or len(content) == 0:
			logger.error("Received empty response from Touchline controller at %s", self._url)
			raise Exception("Touchline controller returned empty response")

		try:
			enc = chardet.detect(content)['encoding']
			return ET.XML(content, parser=ET.XMLParser(encoding=enc))
		except ET.ParseError as e:
			logger.error("Failed to parse XML response from Touchline: %s. Content: %s",
						 str(e), content[:200])  # Log first 200 bytes
			raise Exception(f"Invalid XML response from Touchline controller: {e}")

	def _parse_number_of_devices(self, response):
		item_list = response.find('item_list')
		item = item_list.find('i')
		return item.find('v').text

	def _get_touchline_device_item(self, id):
		items = []
		parameters = ""
		for parameter in self._xml_element_list:
			if parameter.get_type() == Parameter.G:
				parameters += "<n>G%d.%s</n>" % (id, parameter.get_name())
			else:
				parameters += "<n>CD.%s</n>" % (parameter.get_name())
		items.append("<i>" + parameters + "</i>")
		return items

	def get_name(self) -> str | None:
		if "Name" in self._parameter:
			return self._parameter["Name"]
		else:
			return None

	async def set_name_async(self, value: str) -> bool:
		return (await self.write_parameter_async("name",
									value)).decode("utf-8") == str(value)

	def set_name(self, value: str) -> bool:
		return asyncio.run(self.set_name_async(value))

	def get_current_temperature(self) -> float | None:
		if "Temperature" in self._parameter:
			return int(self._parameter["Temperature"]) / self._temp_scale
		else:
			return None

	def get_target_temperature(self) -> float | None:
		if "Setpoint" in self._parameter:
			return int(self._parameter["Setpoint"]) / self._temp_scale
		else:
			return None

	async def set_target_temperature_async(self, value: float) -> bool:
		return (await self.write_parameter_async("SollTemp",
									float(value) *
									self._temp_scale)).decode("utf-8") == \
			   str(float(value) * self._temp_scale)

	def set_target_temperature(self, value: float) -> bool:
		return asyncio.run(self.set_target_temperature_async(value))

	def get_target_temperature_high(self) -> float | None:
		if "Setpoint max" in self._parameter:
			return int(self._parameter["Setpoint max"]) / self._temp_scale
		else:
			return None

	async def set_target_temperature_high_async(self, value: float) -> bool:
		return (await self.write_parameter_async("SollTempMaxVal",
									float(value) *
									self._temp_scale)).decode("utf-8") == \
			   str(float(value) * self._temp_scale)

	def set_target_temperature_high(self, value: float) -> bool:
		return asyncio.run(self.set_target_temperature_high_async(value))

	def get_target_temperature_low(self) -> float | None:
		if "Setpoint min" in self._parameter:
			return int(self._parameter["Setpoint min"]) / self._temp_scale
		else:
			return None

	async def set_target_temperature_low_async(self, value: float) -> bool:
		return (await self.write_parameter_async("SollTempMinVal",
									float(value) *
									self._temp_scale)).decode("utf-8") == \
			   str(float(value) * self._temp_scale)

	def set_target_temperature_low(self, value: float) -> bool:
		return asyncio.run(self.set_target_temperature_low_async(value))

	def get_week_program(self) -> int | None:
		if "Week program" in self._parameter:
			return int(self._parameter["Week program"])
		else:
			return None

	async def set_week_program_async(self, value: int) -> bool:
		return (await self.write_parameter_async("WeekProg",
									value)).decode("utf-8") == str(value)

	def set_week_program(self, value: int) -> bool:
		return asyncio.run(self.set_week_program_async(value))

	def get_operation_mode(self) -> int | None:
		if "Operation mode" in self._parameter:
			return int(self._parameter["Operation mode"])
		else:
			return None

	async def set_operation_mode_async(self, value: int) -> bool:
		return (await self.write_parameter_async("OPMode",
									value)).decode("utf-8") == str(value)

	def set_operation_mode(self, value: int) -> bool:
		return asyncio.run(self.set_operation_mode_async(value))

	def get_device_id(self) -> int | None:
		if "Device ID" in self._parameter:
			return int(self._parameter["Device ID"])
		else:
			return None

	def get_controller_id(self) -> int | None:
		if "Controller ID" in self._parameter:
			return int(self._parameter["Controller ID"])
		else:
			return None

class Parameter(object):
	CD = 0
	G = 1
	R = 2

	def __init__(self, name: str, desc: str, type: int):
		self._name = name
		self._desc = desc
		self._type = type

	def get_name(self) -> str:
		return self._name

	def get_desc(self) -> str:
		return self._desc

	def get_type(self) -> int:
		return self._type
