# Classic Roth Touchline Controller — Community Protocol Notes

> **Scope:** This document describes the local HTTP/XML CGI protocol observed on the **classic Roth Touchline** underfloor heating controller (and compatible OEM variants running the `Keil-EWEB/2.1` embedded web server). It does **not** apply to the newer cloud-based Roth Touchline SL system.
>
> **Disclaimer & Hardware Variance:** These findings were independently reverse-engineered for interoperability by observing HTTP/XML traffic and controller behavior on the author's own hardware. This project is unofficial and is not affiliated with or endorsed by Roth Werke GmbH (all product and brand names are trademarks of their respective owners, referenced solely to identify compatibility). Parameter availability, value scaling, echo formatting, and HTTP server limits **may vary across hardware revisions, OEM variants, and firmware versions**. Provided "as is" under the [MIT License](../LICENSE).

---

## 1. Embedded HTTP Server Behavior & Quirks

The classic Touchline network interface runs on an embedded microcontroller serving a web HMI and CGI endpoints over **`Server: Keil-EWEB/2.1`**.

Several transport constraints were observed during testing and are important for reliable polling (for example in Home Assistant):

1. **1 KiB CGI Response Buffer & Single-Segment POST Ceiling:**
   - Newer hardware/firmware revisions format HTTP response headers (~307 bytes) plus the `ILRReadValues.cgi` XML body into a fixed **`1,024`-byte (`1 KiB`) CGI response buffer**, truncating the XML response mid-tag around **717 bytes** (`unclosed token: line 1, column 715`) if too many keys are requested in one POST.
   - Additionally, `POST /cgi-bin/ILRReadValues.cgi` does **not** reliably reassemble multi-segment HTTP POST bodies (`> ~1,400 bytes`), hanging for 10 seconds if a single request spans multiple TCP segments.
   - Splitting queries into **sequential POST chunks kept below 500 bytes** (at most 10 controller keys or 1 room / 13 keys per POST, yielding ~450–565 byte XML responses) keeps both requests and responses safely inside `Keil-EWEB/2.1` buffers across firmware revisions (~13 ms per request).
2. **Limited Concurrent Socket Capacity:**
   - Issuing concurrent HTTP requests against the same controller IP (for example polling multiple room entities in parallel) can exhaust the embedded TCP socket table and cause intermittent connection drops or 10-second timeouts.
   - Reads and writes targeting the same controller URL should be **serialized** (for example via a single per-controller `asyncio.Lock`).
3. **Plaintext PIN Parameter (`CD.upass`):**
   - Requesting `<n>CD.upass</n>` returns the controller's user PIN in plaintext XML and is **not required** to read or write room or controller parameters. Clients should avoid polling `CD.upass` and must never log raw XML responses that could contain `CD.*` fields.

---

## 2. CGI Endpoints

| Endpoint | Method | Observed Status | Purpose |
|---|---|---|---|
| `/cgi-bin/ILRReadValues.cgi` | `POST` | `200 OK` | Bulk XML parameter read (`Content-Type: text/xml`). |
| `/cgi-bin/writeVal.cgi` | `GET` | `200 OK` | Single query-string parameter write (`?key=value`). |
| `/cgi-bin/readVal.cgi` | `GET` | `200 OK` | Single parameter read (superseded by `ILRReadValues.cgi` for batching). |
| `/cgi-bin/alarm.cgi`, `/cgi-bin/alarm2.cgi` | `GET` | `404 Not Found` | Not enabled on tested controller firmware. |
| `/cgi-bin/trend.cgi` | `GET` | `404 Not Found` | Not enabled on tested controller firmware. |

### 2.1 Bulk Read (`POST /cgi-bin/ILRReadValues.cgi`)

**Request (`Content-Type: text/xml`):**
```xml
<body>
  <version>1.0</version>
  <client>IMaster6_02_00</client>
  <client_ver>6.02.0006</client_ver>
  <file_name>room</file_name>
  <item_list_size>0</item_list_size>
  <item_list>
    <i>
      <n>R0.SystemStatus</n>
      <n>R0.ErrorCode</n>
      <n>G0.name</n>
      <n>G0.RaumTemp</n>
      <n>G0.SollTemp</n>
    </i>
  </item_list>
</body>
```

* `<item_list>` may contain one `<i>` element with multiple `<n>` tags or multiple `<i>` elements.
* Keep the UTF-8 request body **below 500 bytes** (<= 10–13 keys per POST) so the controller's rendered XML response stays well below the **717-byte (`1 KiB` total HTTP)** CGI buffer limit observed on newer firmware revisions.

**Response:**
```xml
<body>
  <version>1.0</version>
  <client>IMaster6_02_00</client>
  <client_ver>6.02.0006</client_ver>
  <item_list_size>1</item_list_size>
  <item_list>
    <i>
      <n>R0.SystemStatus</n><v>0</v>
      <n>R0.ErrorCode</n><v>0</v>
      <n>G0.name</n><v>Office</v>
      <n>G0.RaumTemp</n><v>2267</v>
      <n>G0.SollTemp</n><v>2200</v>
    </i>
  </item_list>
</body>
```

* **Unknown or unsupported keys:** When an unsupported parameter name is requested, the controller may omit `<n>` entirely (leaving an orphan `<v/>`) or return `<v></v>` / `<v>NA</v>`. Parsers **must match `<n>`/`<v>` pairs by tag name** rather than relying on fixed positional offsets.
* **Character encoding:** Room names may be encoded as UTF-8 or Latin-1 / Windows-1252 depending on how they were saved in the web interface; decoding as UTF-8 with an encoding-detection / Windows-1252 fallback avoids decode errors on non-ASCII characters.

### 2.2 Parameter Write (`GET /cgi-bin/writeVal.cgi`)

**Request:**
```http
GET /cgi-bin/writeVal.cgi?G0.SollTemp=2200 HTTP/1.1
```

* **Response:** `HTTP 200 OK` whose body echoes the written value (observed as `2200` or `2200.0`).
* **Temperature scaling:** Temperatures are scaled by **`100`** (`1/100 °C`), e.g. `22.5 °C` -> `2250`. Prefer writing integer hundredths (`int(round(temp_c * 100))`) and validating the echoed response numerically rather than comparing float strings.

---

## 3. Room / Thermostat Parameters (`G0` .. `G{N-1}`)

`totalNumberOfDevices` reports the number of paired room thermostats `N`, addressed as `G0` through `G{N-1}`. Because `G<index>` is a slot index, combining **`ownerKurzID` and `kurzID`** provides a stable per-thermostat identifier.

| Parameter | Access | Scale / Type | Observed Meaning |
|---|---|---|---|
| `G<n>.name` | R/W | `str` | Room display name configured on the controller (e.g. `"Office"`). |
| `G<n>.RaumTemp` | R | `int` (`÷ 100` °C) | Measured room temperature in hundredths of a degree (`2267` = `22.67 °C`). |
| `G<n>.SollTemp` | R/W | `int` (`÷ 100` °C) | Target setpoint temperature (`2200` = `22.00 °C`; room thermostats typically adjust in `0.5 °C` steps). |
| `G<n>.SollTempMinVal` | R/W | `int` (`÷ 100` °C) | Minimum allowed room setpoint (typically `500` = `5.0 °C`). |
| `G<n>.SollTempMaxVal` | R/W | `int` (`÷ 100` °C) | Maximum allowed room setpoint (typically `3000` = `30.0 °C`). |
| `G<n>.SollTempStepVal` | R | `int` (`÷ 100` °C) | Setpoint step metadata (returns `0` on some firmware revisions where the UI step is `0.5 °C`). |
| `G<n>.OPMode` | R/W | `int` enum | Room operating mode: `0` = Normal / Day, `1` = Night, `2` = Off / Holiday. |
| `G<n>.OPModeEna` | R | `int` (`0`/`1`) | Whether operating mode selection is enabled for this room (`1` = enabled). |
| `G<n>.WeekProg` | R/W | `int` enum | Active weekly schedule program: `0` = Off, `1` = Pro 1, `2` = Pro 2, `3` = Pro 3. |
| `G<n>.WeekProgEna` | R | `int` (`0`/`1`) | Whether weekly schedule programs are enabled for this room (`1` = enabled). |
| `G<n>.TempSIUnit` | R/W | `int` enum | Display temperature unit: `0` = `°C`, `1` = `°F`. |
| `G<n>.kurzID` | R | `int` | Short RF thermostat ID (displayed in the thermostat's hardware menu). |
| `G<n>.ownerKurzID` | R | `int` | Short RF ID of the parent controller. |

---

## 4. Controller, Network & Firmware Parameters

### 4.1 Global & Master/Slave Topology

| Parameter | Access | Type / Example | Observed Meaning |
|---|---|---|---|
| `totalNumberOfDevices` | R | `int` (e.g. `7`) | Total number of paired room thermostats exposed as `G0..G{N-1}`. |
| `isMaster` | R | `int` (`0`/`1`) | `1` when this unit is a master controller, `0` when operating as a slave. |
| `numberOfSlaveControllers` | R | `int` (`0..2`) | Number of paired slave controllers (`R1`, `R2`). |

### 4.2 Controller Status & Alarms (`R0.*`, plus `R1.*` / `R2.*` on slaves)

| Parameter | Access | Type / Enum | Observed Meaning |
|---|---|---|---|
| `R0.uniqueID` | R | `str` (24 hex chars) | Controller hardware serial / unique ID (e.g. `0123456789ABCDEF01234567`). Case-sensitive `ID`. |
| `R0.kurzID` | R | `int` (e.g. `10`, `20`) | Short RF controller ID (matches `G<n>.ownerKurzID`). |
| `R0.numberOfPairedDevices` | R | `int` | Number of room units paired directly to `R0`. (`R1`/`R2` also expose `.kurzID`, `.uniqueID`, `.numberOfPairedDevices`.) |
| `R0.OPModeRegler` | R/W | `int` enum (`0..2`) | Controller-wide operating mode applied across paired room units (`0` = Day, `1` = Night, `2` = Off / Holiday; `writeVal.cgi?R0.OPModeRegler=<0..2>` echoes the written integer). Active weekly programs and subsequent local changes on a room unit take priority. |
| `R0.ErrorCode` | R | `int` enum (`0..3`) | Active controller alarm code observed in the web UI:<br>• `0`: No Error<br>• `1`: High Limit Dew Point<br>• `2`: High Limit Supply Water<br>• `3`: RF Communication Interrupted (e.g. lost RF link / depleted thermostat battery) |
| `R0.Safety` | R | `int` (`0`/`1`) | Supply-water safety thermostat flag (`0` = normal). |
| `R0.Taupunkt` | R | `int` (`0`/`1`) | Dew-point sensor flag in cooling setups (`0` = normal). |
| `R0.WeekProgWarn` | R | `int` (`0`/`1`) | Schedule clock warning flag (`1` indicates active schedules may have an invalid clock after power loss). |
| `R0.SystemStatus` | R | `int` | Raw controller status integer (`0` observed during normal heating operation; individual bit meanings are unverified). |
| `R0.DateTime` | R | `int` (Unix seconds) | Controller internal real-time clock timestamp. |
| `R0.HeatCool` | R | `int` | Heating/cooling state (`0` observed in heating mode). |
| `R0.Alarm1` | R | `int` | Auxiliary alarm register (`0` observed). |
| `R0.OutTemp` | R | `int` | Returns sentinel `-30000` when no outdoor sensor is present or supported. |

### 4.3 Network, Firmware & Portal Metadata

| Parameter | Access | Example | Notes |
|---|---|---|---|
| `hw.HostName` | R | `ROTH-000000` | Controller network hostname. |
| `hw.Addr` | R | `00-11-22-33-44-55` | Dash-separated Ethernet MAC address. |
| `hw.IP`, `hw.NM`, `hw.GW`, `hw.DNS1`, `hw.DNS2` | R | IPv4 strings | Current IPv4 network configuration. |
| `STM-APP`, `STM-BL` | R | `A.FA`, `1.20` or `""` | Main controller application & bootloader versions. **Note:** Some hardware/firmware revisions return empty strings `""` for firmware fields, so callers must treat them as optional (`str \| None`). |
| `STELL-APP`, `STELL-BL` | R | `1.42`, `1.20` or `""` | Actuator controller application & bootloader versions (nullable across revisions). |
| `VPI.state`, `VPI.href` | R | `0` / `99`, URL | Remote portal connection status (`0` = disconnected, `1` = connected, `99` = unconfigured, `128` = failed). |
| `CD.uname`, `CD.upass`, `CD.reg`, `CD.save` | R/W | strings | Portal registration & plaintext controller PIN. Avoid reading `CD.upass` during normal operation. |

---

## 5. Observed Hardware Limitations

On tested classic Touchline hardware, the following telemetry was **not** exposed over the CGI/XML interface:

* **No per-zone valve / actuator position or binary output state** (heating demand can only be estimated by comparing `SollTemp > RaumTemp` when not in Off/Holiday mode).
* **No circulation pump or boiler relay state** over CGI.
* **No per-room battery percentage or RF signal strength (RSSI)** (lost RF contact surfaces controller-wide via `R0.ErrorCode == 3`).
* **No floor temperature (`FloorTemp` / `BodenTemp`) or room humidity** parameters on standard room thermostats.
* **No weekly schedule time-slot read/write** for `Pro 1`–`Pro 3` over CGI (time slots are configured locally on the physical thermostat; CGI only switches the active program index `0..3`).

---

## 6. UDP Discovery

The official Roth Touchline app finds controllers on the local network with a UDP broadcast, and `discover_controllers()` uses the same protocol:

* The client broadcasts the ASCII string `SEARCH R*\r\n` to **UDP port 5000**. (`SEARCH R.UID=<unique ID>\r\n` targets a single controller.)
* Every controller answers with a **160-byte** binary packet, sent back to the **source port of the search**, so the client does not need to bind port 5000.

| Bytes | Field | Example | Notes |
|-------|-------|---------|-------|
| 0–3 | Protocol version | `R100` | ASCII |
| 4–5 | Length | `160` | Big-endian |
| 6–7 | Device ID | `37` | Same as `R0.kurzID` and the rooms' `ownerKurzID` |
| 8–9 | Vendor ID | `32` | Roth = `32`; the app ignores other vendors |
| 12–31 | IPv4 address, gateway, netmask, primary DNS, secondary DNS | `192.168.1.14`, … | 4 bytes each |
| 32–37 | MAC address | `5C-C2-13-00-81-49` | Same as `hw.Addr` |
| 48–67 | Name | `ID10655-47951974` | ISO-8859-1, NUL padded; not the hostname |
| 68–147 | Location | `http://192.168.1.14/` | ASCII, NUL padded; the controller's base URL |
| 148–159 | Unique ID | `51FF6E064965525706340287` | 12 bytes, same as `R0.uniqueID` |

Bytes 10–11 and 38–47 were zero on the tested controller.
