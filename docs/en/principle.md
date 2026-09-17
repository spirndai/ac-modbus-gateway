> [中文](../principle.md) | **English**

# Core principle

## 1. Problem and approach

In a York water-system central AC (field-verified panel model MC2100, with RS485), the host controller talks to the wall panels over an RS485 bus using Modbus RTU. The vendor offers no public remote-control interface — but the bus itself is fully visible to the owner. So instead of opening the machine, replacing panels, or waiting for a cloud API that does not exist, we **work on the bus**.

The approach has two steps:

1. **Sniff**: attach the gateway in parallel to the bus (read-only) and forward all host↔panel traffic to the server for parsing — every piece of state (power, mode, temperature, fan speed, water pump) can be read off the bus
2. **Control**: when the server wants to send a command, it hands a standard Modbus write frame to the gateway, which **injects it into the bus while the bus is idle**, writing the target panel's register directly — a panel does not distinguish the source of a command and executes any valid write it receives

All the difficulty lives in step 2: the gateway is an "extra speaker" on an RS485 bus that already has a master. How do we avoid disturbing the original communication? The answer comes from measured bus timing.

### Why control works

The system's normal flow is: **a human operates a panel → the panel updates its own state → the host reads the new settings on its next poll.** On this bus the host only ever *reads*; the panels answer.

Control works for a fundamental reason: **the Modbus RTU protocol itself has no concept of source validation** — a frame carries only a slave address, function code, data and CRC; there is no "sender identity" field. A slave only checks whether the address points to itself and whether the CRC is valid; it cannot and does not care whether the command came from the host or from any other node on the bus. Any node can send a valid write (function code 0x06) and the panel will execute it.

Verified in practice: simulating the host writing to a panel makes the panel act, and the control path reuses the bus's existing mechanism end to end:

```
gateway (write) ──► panel acts ──next poll──► host reads the new state
```

To the panel this is no different from "someone pressed buttons on the panel"; to the host it is just one panel whose settings changed. The whole system stays self-consistent — no participant needs to "know" the gateway exists.

One more corroboration comes from the system's own design: **panels are devices that receive commands by design.** Take mode as an example — panel #1 is the master panel: set it to heating and the whole system switches to heating; set it to cooling and everything switches to cooling. If any panel's mode disagrees with panel #1, the **host actively writes a command** to bring it back in line. In other words, "host writes to panels" is a normal, built-in operating mode of this system; the gateway's injection simply takes the same established path.

## 2. Bus timing analysis (the key)

### Observed bus behaviour

The host (master) polls the panels in turn (each panel has its own address — see "Panel address" in the deployment guide), producing a regular request/response pattern:

```
        one "exchange"
        ├──────────┤
   ┌────┐        ┌──────────────┐        ┌────┐
   │req │ ~10ms  │   response   │ ~100ms │req │  ...
   └────┘        └──────────────┘        └────┘
  8 bytes        69 bytes                next panel
```

Measured timing (9600 8N1, 1 byte = 10 bit ≈ 1.04ms):

| Interval | Measured | Notes |
|---|---|---|
| request → response | ~10ms | panel's answer delay |
| response → next request | **~100ms** | idle bus after the host receives the answer |
| transmission time of one command frame (8 bytes) | ~8.4ms | the minimum needed to inject one frame |

### Deriving the injection window

- An idle gap over **20ms** means the current poll has finished and the next one is at least ~80ms away
- One command frame needs only ~8.4ms to transmit
- Therefore: **injecting one frame after >20ms of idle gives the bus time to return to idle before the next poll — no collision with the master**

This is the core conclusion the whole approach rests on — the gateway's "speaking discipline" is dictated by the bus's own rhythm, not by guesswork.

### Injection state machine in the firmware

```
loop():
    serial data available?
    ├─ yes → bus busy (bus_idle = false), accumulate data
    └─ no  → did the bus just become idle? record last_free_time
             │
             └─ idle ≥ 20ms: do one thing at a time
                 1. pending command → write to the bus after CRC check
                 2. accumulated bus data → report to the server over UDP
                 3. neither → handle OTA
```

Command safeguards:

1. A command frame must pass the **CRC-16 check** before it is written to the bus — garbage never reaches the bus
2. Writing a command and reporting data never happen at the same time (no buffer races)
3. Commands are rate-limited server-side to **≥5s apart** so the bus can settle (`send_udp_packet` in `websvr/utils.py`)

## 3. Data-flow design

### Why the firmware only "ferries" and parsing lives on the server

- Reflashing is expensive: the gateway sits next to the bus and needs physical access (OTA is kept as a fallback)
- Parsing rules may need adjusting per model — on the server that is a Python edit
- Simpler firmware is more reliable: the ESP32 does exactly three things — listen, forward, inject when idle

### Traffic handling on the server

The bus data is extremely repetitive (the host polls every second, but state rarely changes). The server de-duplicates on two levels:

1. **In memory**: identical consecutive register values from the same device are skipped without a database write (`last_state` in `svr.py`)
2. **In the database**: byte-identical messages are stored once (`modbusmsg` with a JSONB hash index); every occurrence only appends a row to `modbustime` — space-efficient and it naturally forms a "state-change timeline"

### Device identification and addressing

The RS485 bus is **one connected system**: all panels and the host hang on the same bus, so **one ESP32 gateway per bus is enough** — mounted at any panel, it hears every panel's traffic and can inject commands for any panel.

- **Panel identity** comes from the slave address in the Modbus frame (set via engineering mode); the server uses it to tell which room a state belongs to
- **Gateway address** is the UDP source IP. The server records it in the `modbusclient` table and, when sending a command, looks up the address for the target panel and sends the command back to the gateway. DHCP changes need no configuration — the next report updates it automatically

> In some environments (some NAS/Docker UDP port-mapping implementations) the container sees the source address rewritten to the gateway IP, which would mis-address commands. In that case run a **host-network UDP proxy** on the server that stamps the real source IP into a packet prefix and forwards to the parser (an earlier version of this deployment did exactly that — it merely moves the source IP from the network layer into the data layer; everything else is identical).

## 4. Comparison with alternatives

| Alternative | Problem |
|---|---|
| IR remote | Send-only: no state feedback, and must point at the panel |
| Opening the unit / rewiring | Risky, warranty-voiding, irreversible |
| Vendor cloud API / official gateway | Does not exist, or extremely expensive |
| Replacing the panels | Costly, and the host↔panel protocol may not be public anyway |
| **Bus tap (this project)** | No modification to any original equipment; both state and control; cost ≈ one ESP32 + one bus transceiver |

## 5. Reliability summary

- **CRC everywhere**: commands are CRC-checked before hitting the bus; responses are CRC-checked when parsed
- **Wi-Fi reconnect**: built into the firmware; parsing rules are unaffected by connectivity loss (resumes after reconnect)
- **Server resilience**: database disconnects are retried and reconnected; invalid/CRC-failing frames are dropped and logged
- **OTA fallback**: once installed, the device is hard to reach physically — ArduinoOTA keeps wireless updates possible
