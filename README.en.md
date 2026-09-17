> [中文](README.md) | **English**

# ac-modbus-gateway

**No network support on your central AC? Take over the bus.**

![York MC2100 panel](docs/images/mc2100.png)

This project targets a York water-system central AC (field-verified panel model **MC2100**, with RS485): the host controller talks to each wall panel over an RS485 Modbus RTU bus, and the vendor offers no remote-control interface (or only an expensive one). We attach an ESP32 gateway in parallel to the bus, **sniff** all host↔panel traffic to reconstruct the AC state, and when control is needed, **inject a standard Modbus write frame into an idle gap on the bus**. A Modbus RTU frame carries no sender identity and the protocol has no source validation — a panel executes any write addressed to it with a valid CRC. Verified in practice: such commands behave exactly like manual operation on the panel, and the panel reports the new state to the host on its next poll.

The AC equipment and vendor firmware are not modified, and the original communication is untouched. The hands-on work happens at a panel: data can be tapped from the RS485 connector on the panel's back (no disassembly needed, but an external power supply is required); or disassemble one more layer to also tap DC 12V and drop the external PSU (see the deployment guide).

> This is a personal home project (7 panels) that has run reliably for a long time, and the injection strategy is field-verified. But it is **not an engineered product** — it has not been validated in other environments and may not work in yours; the author is not an HVAC/electronics professional. Attempt it only with sufficient technical skill — wiring mistakes can burn your equipment. Use at your own risk (see the disclaimer at the end).

## Features

- **Non-invasive bus tap**: the gateway only listens in parallel; control frames are injected into the measured idle window of the bus and do not disturb the original traffic (no changes to the AC equipment or vendor firmware)
- **Monitoring**: power, operating mode (cool / heat / fresh air / floor heating / floor heating + heat), target temperature, current temperature, fan speed, water pump state
- **Control**: power on/off, mode, target temperature, fan speed, water pump
- **Protocol reverse engineering**: register meanings were reconstructed by diffing bus responses before/after panel operations (register table in the protocol doc)
- **Minimal firmware**: the ESP32 only ferries raw frames (report + idle injection); parsing, de-duplication and storage all live on the server, so logic changes never require reflashing
- **Complete pipeline**: state stored in PostgreSQL, mobile-friendly web UI for viewing and control
- **Auto addressing**: the server learns the gateway IP from the source address of incoming packets (no config on DHCP changes) and sends control commands back to the gateway

## Architecture

```
                    RS485 bus
      host(controller) ◄─┬──────► panels (independent addresses)
                         │
        parallel sniff (read-only) + inject when idle
                         │
                  ┌──────┴────┐
                  │   ESP32   │  WiFi gateway (firmware/)
                  └──────┬────┘
        UDP:12333 report │ ▲ UDP:12335 control commands
                         ▼ │
                  ┌───────┴────┐     ┌────────────┐
                  │    svr     │────►│ PostgreSQL │
                  │ parse      │     └────────────┘
                  │ store      │
                  └────────────┘
                  ┌────────────┐
                  │  websvr    │  browser/phone view & control
                  └────────────┘  (reads DB for state, sends UDP commands to the gateway)
```

## Documentation

| Document | Content |
|---|---|
| [docs/en/principle.md](docs/en/principle.md) | **Core principle**: bus timing analysis, idle-window injection strategy, data-flow design |
| [docs/en/protocol.md](docs/en/protocol.md) | **Protocol**: Modbus frame layout, reverse-engineering method, register table, UDP interface, database schema |
| [docs/en/deployment.md](docs/en/deployment.md) | **Deployment**: hardware wiring, firmware flashing, server setup, troubleshooting |

(Chinese versions: [docs/principle.md](docs/principle.md), [docs/protocol.md](docs/protocol.md), [docs/deployment.md](docs/deployment.md))

## Quick start

```bash
# Server (change your_db_password in docker-compose.yml first)
cd server && docker compose up -d

# Firmware: open firmware/udp_to_modbus/udp_to_modbus.ino in the Arduino IDE,
# edit the WiFi / server address / OTA password at the top, then flash
```

Open `http://<server-ip>:9950` in a browser to view and control. Details in [docs/en/deployment.md](docs/en/deployment.md).

> **Language note**: this README and the docs are also available [in Chinese](README.md). The web UI and message texts are in Chinese — to localize them, hand the templates and strings to an AI (e.g. Claude); that is simpler than building i18n into the project.

## Repository layout

```
firmware/udp_to_modbus/    ESP32 firmware (Arduino, WiFi version)
server/
  docker-compose.yml       service orchestration
  svr/                     UDP receive, Modbus frame parsing, database storage
  websvr/                  Flask web UI (state display + control)
docs/                      documentation (Chinese at docs/, English at docs/en/)
```

## Disclaimer

- This project originates from **personal home use**. It has run reliably for a long time, but it is **not an engineered product** — it has not been validated across environments and may not work on your equipment
- The author is not an HVAC/electronics professional; this is a **reference approach** only. Attempt it only if you have sufficient technical skills (disassembly, wiring, embedded, networking)
- Wiring mistakes, wrong voltages and accidental contact can **destroy equipment** (the transceiver module, the ESP32, even the AC panel) — assess the risk yourself
- This is an unofficial personal project, not affiliated with or endorsed by York or any related vendor
- The protocol and register information was obtained by observing and analyzing the communication bus of **the author's own equipment**, for learning, research and interoperability purposes only
- Touching the AC bus and changing operating parameters (especially the water pump registers) may affect normal operation or damage equipment, and may void the warranty — **at your own risk**
- This project contains no vendor firmware, manuals or other copyrighted material

## License

[GPL-3.0](LICENSE)
