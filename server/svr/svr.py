#!/usr/bin/python3
# Receives raw frames sniffed from the AC bus, parses Modbus RTU frames
# and stores them in PostgreSQL.

import os
import json
import socket
import psycopg2
import crcmod

crc16 = crcmod.predefined.mkPredefinedCrcFun("modbus")

UDP_PORT = 12333  # gateways report here; svr runs with host networking


def connect_db():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        database=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
        connect_timeout=10,
    )


conn = connect_db()

from initdb import init_db

init_db(conn)


class InvalidError(Exception):
    pass


def parse_modbus_frame(frame):
    """Parse one Modbus RTU frame, return (record, frame_len).

    Byte[2] == 0 marks a request frame (high byte of the register address),
    anything else is a response frame (byte count for 0x03/0x04).
    """
    record = {}
    is_request = frame[2] == 0
    record["type"] = "request" if is_request else "response"

    device_address = frame[0]
    if device_address not in range(1, 11):
        raise InvalidError("bad device address")
    function_code = frame[1]
    if function_code not in (1, 2, 3, 4, 5, 6, 0x10):
        raise InvalidError("bad function code")
    record["dev_address"] = device_address
    record["function_code"] = function_code

    if is_request:
        frame_len = 8
        if len(frame) < frame_len:
            raise InvalidError("short frame")
        if function_code in (1, 2, 3, 4):
            record["read_addr"] = (frame[2] << 8) | frame[3]
            record["data_len"] = (frame[4] << 8) | frame[5]
        elif function_code in (5, 6):
            record["write_addr"] = (frame[2] << 8) | frame[3]
            record["value"] = (frame[4] << 8) | frame[5]
        else:  # 0x10 write multiple registers
            byte_count = frame[6]
            frame_len = 9 + byte_count
            if frame_len > 100 or len(frame) < frame_len:
                raise InvalidError("bad frame length")
            record["write_list"] = (frame[2] << 8) | frame[3]
            record["data_len"] = (frame[4] << 8) | frame[5]
            record["byte_count"] = byte_count
    else:
        if function_code in (1, 2, 3, 4):
            byte_count = frame[2]
            frame_len = 5 + byte_count
            if frame_len > 100 or len(frame) < frame_len:
                raise InvalidError("bad frame length")
            record["byte_count"] = byte_count
            if function_code in (1, 2):
                record["data"] = frame[3:3 + byte_count].hex()
            else:  # 0x03/0x04: split data into 16-bit register values
                record["register_values"] = [
                    (frame[3 + i] << 8) | frame[4 + i]
                    for i in range(0, byte_count, 2)
                ]
        elif function_code in (5, 6):
            frame_len = 8
            if len(frame) < frame_len:
                raise InvalidError("short frame")
            record["addr"] = (frame[2] << 8) | frame[3]
            record["value"] = (frame[4] << 8) | frame[5]
        else:  # 0x10
            frame_len = 8
            if len(frame) < frame_len:
                raise InvalidError("short frame")
            record["start_addr"] = (frame[2] << 8) | frame[3]
            record["data_len"] = (frame[4] << 8) | frame[5]

    # Requests often carry a stale CRC, only validate responses (frame_len > 8)
    if frame_len > 8:
        crc_recv = (frame[frame_len - 1] << 8) | frame[frame_len - 2]
        if crc_recv != crc16(bytes(frame[:frame_len - 2])):
            raise InvalidError(f"CRC mismatch, dev {device_address}")

    return record, frame_len


last_state = {}


def insert_to_db(record, ipaddr):
    """Store a parsed frame; consecutive unchanged states are skipped."""
    global conn

    key = value = ""
    if record["type"] == "request" and record["function_code"] == 3:
        key, value = f"request{record['dev_address']}", 1
    elif (record["type"] == "response" and record["function_code"] == 3
          and "register_values" in record):
        key = f"response{record['dev_address']}"
        value = "".join(f"{d:04x}" for d in record["register_values"])
    if key:
        if last_state.get(key) == value:
            return True  # unchanged, skip
        last_state[key] = value

    data = json.dumps(record)
    print(data)

    def _write():
        cursor = conn.cursor()
        # identical messages are stored once, modbustime records each occurrence
        cursor.execute("SELECT id FROM modbusmsg WHERE msg = %s", (data,))
        row = cursor.fetchone()
        if row:
            msg_id = row[0]
        else:
            cursor.execute(
                "INSERT INTO modbusmsg (msg) VALUES (%s) RETURNING id", (data,))
            msg_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO modbustime (msg_id, insert_time) VALUES (%s, now())",
            (msg_id,))
        cursor.execute(
            "INSERT INTO modbusclient (device_id, ipaddr) VALUES (%s, %s) "
            "ON CONFLICT (device_id) DO UPDATE SET ipaddr = %s",
            (record["dev_address"], ipaddr, ipaddr))
        conn.commit()
        return bool(row)

    try:
        return _write()
    except psycopg2.Error as e:
        print("db error:", e)
        conn.rollback()
        try:
            conn = connect_db()
        except psycopg2.Error as e2:
            print("db reconnect failed:", e2)
        return False


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"UDP server listening on {UDP_PORT}")

    while True:
        data, addr = sock.recvfrom(1024)
        # the UDP source address identifies which gateway sent the data
        client_ip = addr[0]
        payload = data
        if len(payload) not in (69, 77):
            continue

        # a payload may contain several concatenated frames (77 = request + response)
        while len(payload) > 4:
            try:
                record, frame_len = parse_modbus_frame(payload)
            except InvalidError as e:
                print("invalid:", payload.hex(), e)
                break
            except IndexError:
                print("index error:", payload.hex())
                break

            existed = insert_to_db(record, client_ip)
            if not existed:
                print("new:", payload[:frame_len].hex())

            if frame_len < len(payload):
                payload = payload[frame_len:]  # more frames in this packet
            else:
                break


if __name__ == "__main__":
    main()
