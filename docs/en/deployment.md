> [中文](../deployment.md) | **English**

# Deployment guide

> **Read before you start**: this project originates from personal home use. It has run reliably for a long time, but it is **not an engineered product** and no guarantee is made that it works in your environment. The work involves opening a panel, wiring and tapping power — **wiring mistakes, wrong voltages and accidental contact can destroy equipment** (the transceiver module, the ESP32, even the panel). Proceed only if you have sufficient technical skill, at your own risk.

## 1. Bill of materials

| Item | Notes |
|---|---|
| ESP32-C3 board | one per bus; other ESP32 models work too (adjust the GPIO pins) |
| RS485-to-TTL auto-direction module | MAX485ESA + 74HC04D on board (see §2), ~1 CNY on Taobao — **buy a few spares** |
| DC-DC buck module | 12V→3.3V/5V (e.g. mini560 / MP1584, a few CNY); taps 12V from the inner 10p cable (option B) |
| AC-to-DC power adapter | needed only for option A (no disassembly), to power the ESP32 |
| 1.25mm connectors / thin wires | to tap 12V/GND/A/B from the inner 10p cable |
| Server | any x86/ARM Linux box with Docker, preferably always-on |

## 2. Hardware wiring

There are two ways to tap data (RS485) and power — pick what suits you:

| Option | Data source | Power | Disassembly |
|---|---|---|---|
| A | the RS485 connector reserved on the panel's back (originally for building control / BMS) | external AC-to-DC adapter | none |
| B (used here) | disassemble to the inner layer, tap A/B from the 10p cable | DC 12V from the same 10p cable (via a DC-DC buck) | down to the inner layer |

The panel used in this project is a York MC2100 (photo below):

![MC2100 panel](../images/mc2100.png)

**Option B**: the panel has to be opened two layers deep:

1. The panel's back side carries the vendor-reserved RS485 connector (meant for building control / BMS), but that area has **only AC, no DC** — it cannot power the ESP32
2. **Disassemble one more layer** (the board with the MCU) and you will find a **10-pin, 1.25mm-pitch cable** carrying **12V, GND, RS485 A/B**, plus the panel's relay control signals

Tap four wires out of this 10p cable — **12V, GND, RS485 A, RS485 B**:

- **12V** → DC-DC buck module to 3.3V/5V, powering the ESP32 and the transceiver module — **with DC 12V available inside, no external AC-to-DC adapter is needed, just a buck converter**
- **A / B** → the bus side of the RS485-to-TTL module
- **GND** → common ground with the buck module, ESP32 and transceiver (power ground only; the differential signal itself needs no grounding treatment)
- Transceiver TTL side: **TXD → GPIO6 (RX)**, **RXD → GPIO7 (TX)**

```
   Open the panel down to the inner layer, tap four wires (12V/GND/A/B):

       12V ──────► [DC-DC buck 12V→3.3V/5V] ──────► powers ESP32 & transceiver
       GND ──────► common ground (ESP32, transceiver, buck)
       A  ──┐
       B  ──┴───► [RS485-to-TTL module] ──TXD/RXD──► ESP32 GPIO6/GPIO7
```

The transceiver is an **RS485-to-TTL auto-direction module** (MAX485ESA + 74HC04D; it switches direction automatically — **no DE/RE pin to drive from the MCU**, the firmware simply uses Serial1):

![RS485-to-TTL auto-direction module](../images/rs485_ttl_module.jpg)

> The photo shows two modules; one per ESP32 is enough. They cost about 1 CNY each — **keep spares**: a wiring mistake easily kills the module, and swapping in a fresh one gets you going again.

Module pin mapping:

| Module side | Pin | Connects to |
|---|---|---|
| TTL side | VCC / GND | buck module output (3.3V or 5V, per the module's requirement) |
| TTL side | TXD | ESP32 **GPIO6 (RX)** |
| TTL side | RXD | ESP32 **GPIO7 (TX)** |
| Bus side | A / B | A / B of the panel's 10p cable |

Key points:

- **For monitoring only, TXD alone is enough** (the module's transmit pin); connect RXD too if you want control
- **Double-check the order of the four wires in the 10p cable** (12V/GND/A/B) — the cable also carries the panel's relay control signals; miswiring 12V can burn the module and even damage the panel
- RS485 is differential and the tap is only a few centimetres long: **no interference, no grounding/shielding needed** — just tap in parallel
- Match the TXD output level to your MCU (a 5V-powered module outputs 5V on TXD; power the ESP32 from 3.3V or add level shifting)
- For **option A** (no disassembly): tap data from the reserved RS485 connector and power the ESP32 from an external adapter; the rest of the wiring is identical
- Opening the panel and wiring may void the warranty — judge for yourself

### Panel address (engineering mode)

Each panel's slave address is configured in the **MC2100's engineering mode** and is normally set at installation time — no changes needed (the **count depends on the installation**; this deployment has 7 panels, addresses 1~7):

- **Entering the engineering mode, the first value shown is this panel's address**
- That address is the `dev_address` the server parses — it determines which room a state or command belongs to
- If an address never produces data, first check that the panel address is within the range the server accepts (1~10 by default) and not duplicated on another panel

## 3. Flashing the firmware

1. Install the ESP32 board package in the Arduino IDE (search "esp32" in the Boards Manager)
2. Open `firmware/udp_to_modbus/udp_to_modbus.ino`
3. Edit the configuration at the top of the file:

```cpp
const char* ssid = "your_wifi_ssid";        // your Wi-Fi
const char* password = "your_wifi_password";
#define udpServerIP 192, 168, 1, 100        // server address
...
ArduinoOTA.setPassword("your_ota_password"); // set your own OTA password
```

4. Select the board (e.g. `ESP32C3 Dev Module`) and the serial port, then flash
5. When the serial monitor (115200) shows `WiFi connecting....IP: x.x.x.x`, you are up
6. The device can later be updated wirelessly via ArduinoOTA (appears as `acmon_wifiXXXX` in the network ports)

## 4. Server deployment

```bash
cd server
# edit docker-compose.yml:
#   your_db_password → your own database password
docker compose up -d
```

Services:

| Service | Ports | Role |
|---|---|---|
| svr | UDP 12333 (host network) | receives gateway data, parses Modbus frames, stores to DB |
| websvr | 9950 → container 5000 | web view & control |
| db | 127.0.0.1:5432 | PostgreSQL (tables created automatically on first start) |

`svr` uses **host networking** so that the gateway's UDP source IP is preserved — command addressing depends on it.

If you already have PostgreSQL, just point the services at it.

## 5. Verification

```bash
# 1. Follow the parse log; it should print JSON messages continuously
docker compose logs -f svr

# 2. Open the web UI in a browser; each room's live state should appear
#    http://<server-ip>:9950

# 3. Test control (set panel 2's target temperature to 25°C)
cd server/svr
python3 send_cmd.py <gateway-ip> 2 4 250
```

After a control command takes effect, the panel and the web UI show the new state on the next poll.

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| No data at the server | gateway not on Wi-Fi; server firewall blocking UDP 12333 |
| Garbled log / CRC mismatch | baud rate not 9600; tap wires too long picking up interference (the few-cm tap here does not); signal not going through a transceiver |
| Suddenly no data after rewiring | the transceiver module was probably burnt while wiring (very common) — try a spare |
| Web shows state but control does nothing | commands go directly to the gateway IP on port 12335; check the gateway IP against the `modbusclient` table; commands must be ≥5s apart |
| A panel's mode reverts after being changed | expected: panel #1 is the master panel and its mode wins — change the mode by writing panel #1 |
| One device never appears | its panel address (first value in engineering mode) must be within the server's accepted range and not duplicated; make sure it is being polled on the bus |
| Data looks stale | by design, state is only stored when it changes; the last update time is shown on the detail page |

## 7. Security notes

- The web UI has **no authentication** — run it on a trusted LAN only, never expose it to the internet
- Do not keep the example database and OTA passwords
