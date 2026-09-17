#!/usr/bin/python3
# CLI tool: send a Modbus write command (function 0x06) to a gateway device.
# Usage: send_cmd.py <device_ip> <device_address> <register> <value>
#
# Register map (reverse-engineered, see docs/protocol.md):
#   2 power 0/1, 3 mode 1-5, 4 target temp x10, 5 fan 0-3 (0=high),
#   22 water pump 0=off 1=cooling pump 2=heating pump

import socket
import struct
import sys


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


def build_write_packet(slave_address, register_address, register_value):
    packet = struct.pack(">BBHH", slave_address, 0x06,
                         register_address, register_value)
    return packet + struct.pack("<H", calculate_crc(packet))


def send_udp_packet(ip, port, packet):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(packet, (ip, port))
    sock.close()
    print(f"sent to {ip}:{port}: {packet.hex(' ')}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("usage: send_cmd.py <device_ip> <device_address> <register> <value>")
        sys.exit(1)
    ip = sys.argv[1]
    dev_addr, register, value = (int(x) for x in sys.argv[2:5])
    send_udp_packet(ip, 12335, build_write_packet(dev_addr, register, value))
