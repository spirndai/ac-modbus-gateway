> [中文](../protocol.md) | **English**

# Protocol

## 1. Bus protocol: Modbus RTU

Physical layer: RS485 half-duplex, 9600 8N1. A single master (the host controller) polls the panels cyclically (each panel has its own slave address, configured via the panel's engineering mode), using standard Modbus RTU frames. A frame has four parts:

```
┌────────────┬─────────────┬──────────────┬────────────────────┐
│ slave addr │ function    │ data field   │ CRC16 (LSB first)  │
│  1 byte    │  1 byte     │   N bytes    │      2 bytes       │
└────────────┴─────────────┴──────────────┴────────────────────┘
```

| Field | Length | Notes |
|---|---|---|
| Slave address | 1 byte | address of the target panel (set via engineering mode; 1~7 in this deployment) |
| Function code | 1 byte | two are used on this bus: 0x03 read holding registers, 0x06 write single register |
| Data field | N bytes | depends on the function code, see the next sections |
| CRC16 | 2 bytes | Modbus CRC-16 (polynomial 0xA001, init 0xFFFF), least-significant byte first |

> There is **no "sender identity" field** in a frame; the slave only checks the address and the CRC — this is what makes the control path of this project possible.

## 2. Frames observed on the bus

### Read request (8 bytes)

The host reads a panel's full state: 32 consecutive registers starting at address 1 (function 0x03). Example, polling panel 7:

```
07 03 00 01 00 20 15 B4
```

| Byte | Value | Field | Meaning |
|---|---|---|---|
| 0 | 07 | slave address | panel 7 |
| 1 | 03 | function code | read holding registers |
| 2~3 | 00 01 | start address | register address 1 (big-endian) |
| 4~5 | 00 20 | register count | 0x20 = 32 |
| 6~7 | 15 B4 | CRC16 | low byte 0x15 first |

### Read response (69 bytes)

```
AA 03 40 [64 bytes of register data] CRCL CRCH
```

| Byte | Value | Field | Meaning |
|---|---|---|---|
| 0 | AA | slave address | matches the request |
| 1 | 03 | function code | read holding registers |
| 2 | 40 | byte count | 0x40 = 64 = 32 registers × 2 bytes |
| 3~66 | … | register data | 32 big-endian 16-bit values; **register address = 1 + index** (the k-th value is address 1+k) |
| 67~68 | CRCL CRCH | CRC16 | least-significant byte first |

### Write command (8 bytes, the control frame this project sends)

```
AA 06 00 RR 00 VV CRCL CRCH
```

| Byte | Field | Meaning |
|---|---|---|
| 0 | slave address | target panel |
| 1 | function code | 0x06 write single register |
| 2~3 | register address | big-endian |
| 4~5 | value | big-endian |
| 6~7 | CRC16 | least-significant byte first |

No reply is awaited after sending; the authoritative state is the host's report on its next poll (the web UI auto-refreshes roughly every 30 seconds).

### Packets reported by the gateway

The firmware reports raw chunks of bus data as received; the server accepts only two lengths:

| Length | Content |
|---|---|
| 69 bytes | one response frame |
| 77 bytes | request frame (8 bytes) + response frame (69 bytes), back to back |

Frames that fail the CRC check are dropped — not parsed, not stored.

## 3. How the registers were reverse-engineered

The register meanings do not come from any public document; they were reconstructed by **comparison**:

1. Operate one known function on the panel (e.g. change the temperature from 24 to 25)
2. Capture the response frames before and after, diff them byte by byte
3. The changed byte position → the register → the function

Repeat for every function (power, mode, fan, water pump) and the table below falls out.

## 4. Register map

> The mapping below was **verified on the actual equipment** of this project; other models/batches may differ — verify with the comparison method above.

### State readout (64-byte data field of a response)

| Register address | Data index | Meaning | Values |
|---|---|---|---|
| 2 | 1 | power | 0=off 1=on |
| 3 | 2 | operating mode | 1=cool 2=heat 3=fresh air 4=floor heating 5=floor heating + heat |
| 4 | 3 | target temperature | temp ×10 (250 = 25.0°C) |
| 5 | 4 | fan speed | 0=high 1=mid 2=low 3=auto |
| 16 | 15 | current temperature | temp ×10 |
| 23 | 22 | water pump / floor heating state | non-zero = on |

### Control writes (function 0x06, write single register)

| Register address | Function | Values |
|---|---|---|
| 2 | power | 0=off 1=on |
| 3 | operating mode | 1~5, as above |
| 4 | target temperature | temp ×10 |
| 5 | fan speed | 0~3, as above |
| 22 | water pump control | 0=off 1=cooling pump 2=heating pump |

How it works: **Modbus RTU has no source validation** — a frame contains no sender identity, and the slave only checks the address and CRC. And as the principle doc explains, "host writes to panels" is a normal flow of this York system; panels are built to execute received write commands. A command frame can therefore be sent straight to a panel (emulating the host's write); the panel acts, and reports the new state to the host on the next poll. The control path is fully equivalent to operating the panel by hand.

> **Mode control caveat**: panel #1 is the master panel — its mode defines the system-wide mode (set #1 to heat and every panel heats; likewise for cool), and the host brings divergent panels back in line. So **change the mode by writing to panel #1**; changing another panel's mode alone will be reverted by the host.

### Capability overview (what can be monitored / controlled)

| Function | Monitor (read) | Control (write) | Values |
|---|---|---|---|
| Power | ✓ register 2 | ✓ write register 2 | 0=off 1=on |
| Operating mode | ✓ register 3 | ✓ write register 3 | 1=cool 2=heat 3=fresh air 4=floor heating 5=floor heating + heat |
| Target temperature | ✓ register 4 | ✓ write register 4 | ×10, e.g. 250 = 25.0°C |
| Current temperature | ✓ register 16 | — (sensor value, read-only) | ×10 |
| Fan speed | ✓ register 5 | ✓ write register 5 | 0=high 1=mid 2=low 3=auto |
| Water pump / floor heating | ✓ register 23 | ✓ write register 22 | write: 0=off 1=cooling pump 2=heating pump |

- **Monitoring** (state reporting): web UI display, database storage
- **Control** (command downlink): via the web UI or the `send_cmd.py` CLI; commands are written to the target panel inside an idle window of the bus
- The above are the confirmed registers; the bus may carry other functions that have not been reverse-engineered

## 5. Gateway ↔ server UDP protocol

```
gateway ── report ──►  :12333  svr (identifies devices from the UDP source address)
gateway ◄─ control ──  :12335  (sent directly by websvr / svr)
```

- **Report**: the gateway sends raw bus data over UDP to the server's port 12333. The panel identity comes from the **slave address** inside the Modbus frame; the packet's **source IP** (the gateway address) is recorded in the `modbusclient` table for addressing commands
- **Control**: the complete 8-byte Modbus 0x06 frame is sent directly to the gateway's port 12335; the gateway checks the CRC and writes it to the bus when idle
- At least 5 seconds between commands

## 6. Database schema (PostgreSQL)

Messages are stored on two levels, "content + time", so duplicates keep only one copy of the content:

| Table | Columns | Notes |
|---|---|---|
| `modbusmsg` | id, msg (JSONB) | parsed messages; byte-identical content stored once; hash index on `msg` |
| `modbustime` | id, insert_time, msg_id | one row per occurrence — the state-change timeline |
| `modbusclient` | device_id, ipaddr | panel address → gateway IP (learned from the report's source address); used to address commands |

Example `modbusmsg.msg` (parse result of one response frame):

```json
{"type": "response", "dev_address": 2, "function_code": 3,
 "byte_count": 64, "register_values": [0, 1, 1, 250, 3, ...]}
```
