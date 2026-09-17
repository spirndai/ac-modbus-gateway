#!/usr/bin/python3
# Device state queries and control commands for the web UI.

import socket
import struct
import time
import os
from datetime import datetime, timedelta

import psycopg2


def get_conn():
    return psycopg2.connect(
        host="db",
        database=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
        connect_timeout=10,
    )


# --- Modbus helpers ---

def calculate_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc


def build_modbus_packet(slave_address, register_address, register_value):
    """Build a Modbus write-single-register command (function 0x06)."""
    packet = struct.pack(">BBHH", int(slave_address), 0x06,
                         register_address, int(register_value))
    return packet + struct.pack("<H", calculate_crc(packet))


UDP_PORT = 12335  # gateway command port


def send_udp_packet(ip, port, packet):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(packet, (ip, port))
    sock.close()
    print(f"sent Modbus packet to {ip}:{port}")
    # keep at least 5s between commands so the bus can settle
    time.sleep(5)


# --- Device control, register map: see docs/protocol.md ---

def device_close(address):
    send_udp_packet(get_client(address), UDP_PORT,
                    build_modbus_packet(address, 2, 0))


def device_open(address):
    send_udp_packet(get_client(address), UDP_PORT,
                    build_modbus_packet(address, 2, 1))


def device_set_temp(address, temp):  # temp is x10, e.g. 250 = 25.0
    send_udp_packet(get_client(address), UDP_PORT,
                    build_modbus_packet(address, 4, temp))


def device_set_fan(address, fan):  # 0 high 1 mid 2 low 3 auto
    send_udp_packet(get_client(address), UDP_PORT,
                    build_modbus_packet(address, 5, fan))


def device_set_mode(address, mode):  # 1 cool 2 hot 3 fresh 4 floor 5 floor+hot
    send_udp_packet(get_client(address), UDP_PORT,
                    build_modbus_packet(address, 3, mode))


def device_close_heating(address):
    # 22: water pump, 0=off 1=cooling pump 2=heating pump
    send_udp_packet(get_client(address), UDP_PORT,
                    build_modbus_packet(address, 22, 0))


def get_client(address):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT ipaddr FROM modbusclient WHERE device_id = %s", (address,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result:
        return result[0]
    return "127.0.0.1"


def devicesinfo():
    """Latest 0x03 response of every device."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT DISTINCT ON (m.msg->>'dev_address') m.id, m.msg, t.insert_time
        FROM modbusmsg m JOIN modbustime t ON m.id = t.msg_id
        WHERE (m.msg->>'function_code')::int = 3
          AND m.msg->>'type' = 'response'
        ORDER BY m.msg->>'dev_address', t.insert_time DESC;
    ''')
    result = cur.fetchall()
    cur.close()
    conn.close()

    ret = []
    for i in result:
        k = i[1]
        now = datetime.now()
        delta = now - i[2] if now > i[2] else i[2] - now
        if delta <= timedelta(hours=24):
            k['insert_time'] = i[2].strftime("%H:%M")
        else:
            k['insert_time'] = i[2].strftime("%m-%d")
        ret.append(k)
    return ret
