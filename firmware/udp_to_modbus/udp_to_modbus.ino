/*
 * AC bus gateway firmware (ESP32, WiFi version)
 *
 * Listens on the Modbus RTU bus between the AC host controller and the
 * wall panels:
 *   - frames seen on the bus are forwarded to the server over UDP as-is
 *   - control commands pushed by the server are injected into the bus
 *     while it is idle, so the original host<->panel communication
 *     is not disturbed
 *
 * Hardware: GPIO6 (RX) / GPIO7 (TX), 9600 8N1, wired to the bus through an
 * auto-direction RS485-to-TTL module (no DE/RE pin needed). Powered from
 * the panel's 12V rail through a buck converter.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include "AsyncUDP.h"
#include <Ticker.h>

Ticker timer;
volatile unsigned long mymillis = 0;
void onTimer() {
  mymillis++;
}

// ===== change to your own settings =====
const char* ssid = "your_wifi_ssid";
const char* password = "your_wifi_password";
#define udpServerIP 192, 168, 1, 100  // server address
// =======================================

const int udpServerPort = 12333;  // bus data is reported here
const int localUdpPort = 12335;   // control commands arrive here

AsyncUDP udp;

#define BAUD 9600
#define RXPIN 6
#define TXPIN 7

uint8_t uartbuf[64];  // command frame from the server, sent when the bus is idle
uint8_t uartbuf_len = 0;

String getmac() {
  uint8_t mac[6];
  WiFi.macAddress(mac);

  String macStr;
  for (int i = 0; i < 6; i++) {
    if (i > 0) macStr += "-";
    if (mac[i] < 0x10) macStr += "0";
    macStr += String(mac[i], HEX);
  }
  macStr.toUpperCase();
  return macStr;
}

void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(WIFI_PS_MIN_MODEM);
  WiFi.begin(ssid, password);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nIP: %s\n", WiFi.localIP().toString().c_str());

  // bus serial
  Serial1.begin(BAUD, SERIAL_8N1, RXPIN, TXPIN);
  timer.attach_ms(1, onTimer);

  // receive control commands from the server
  if (udp.listen(localUdpPort)) {
    udp.onPacket([](AsyncUDPPacket packet) {
      // drop the frame if a previous one is still waiting to be sent
      if (packet.length() <= sizeof(uartbuf) && uartbuf_len == 0) {
        memcpy(uartbuf, packet.data(), packet.length());
        uartbuf_len = packet.length();
      }
    });
  }
  Serial.println("UDP ready");

  // OTA hostname "acmon_wifi" + last 4 bytes of the MAC, unique per device
  String mac = getmac();
  String macSuffix = mac.substring(mac.length() - 5);
  macSuffix.replace("-", "");
  String otaName = "acmon_wifi" + macSuffix;
  ArduinoOTA.setHostname(otaName.c_str());
  ArduinoOTA.setPassword("your_ota_password");
  ArduinoOTA.begin();
  Serial.printf("OTA name: %s\n", otaName.c_str());
}

int last_free_time = 0;
bool bus_idle = false;
uint8_t data_buf[512];  // data seen on the bus
int data_buf_pos = 0;

// Forward bus data to the server; parsing and de-duplication happen there
void forward_data_buf() {
  if (data_buf_pos == 0) return;
  udp.writeTo(data_buf, data_buf_pos, IPAddress(udpServerIP), udpServerPort);
  data_buf_pos = 0;
}

void loop() {
  delay(10);

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected, reconnecting...");
    WiFi.reconnect();
    delay(3000);
  }

  int p = Serial1.available();
  if (p > 0) {
    bus_idle = false;

    if (p + data_buf_pos > sizeof(data_buf)) {  // buffer full, flush it first
      forward_data_buf();
      while (p > sizeof(data_buf)) {
        Serial1.readBytes(data_buf, sizeof(data_buf));
        p -= sizeof(data_buf);
        data_buf_pos = sizeof(data_buf);
        forward_data_buf();
      }
    }
    if (p > 0) {
      Serial1.readBytes(&(data_buf[data_buf_pos]), p);
      data_buf_pos += p;
    }
  } else {
    if (!bus_idle) {
      bus_idle = true;
      last_free_time = mymillis;  // bus just became idle
    }
    // Measured on the real bus: ~100ms idle between commands, ~10ms between
    // a query and its reply. An idle gap over 20ms guarantees at least ~80ms
    // of free bus, which is enough to inject one command frame safely.
    if (mymillis - last_free_time >= 20) {
      if (uartbuf_len > 0) {
        send_command(uartbuf, uartbuf_len);
        uartbuf_len = 0;
        Serial.println("sent command");
      } else if (data_buf_pos > 0) {
        forward_data_buf();
      } else {
        ArduinoOTA.handle();
      }
    }
  }
}

// Modbus CRC-16
uint16_t calculateCRC(uint8_t* data, uint8_t length) {
  uint16_t crc = 0xFFFF;

  for (uint8_t i = 0; i < length; i++) {
    crc ^= (uint16_t)data[i];
    for (uint8_t j = 0; j < 8; j++) {
      if (crc & 0x0001) {
        crc >>= 1;
        crc ^= 0xA001;
      } else {
        crc >>= 1;
      }
    }
  }

  return crc;
}

bool checkModbusCRC(uint8_t* data, uint8_t length) {
  if (length < 2) return false;

  uint16_t calculatedCRC = calculateCRC(data, length - 2);
  uint16_t receivedCRC = (uint16_t)data[length - 1] << 8 | data[length - 2];

  return (calculatedCRC == receivedCRC);
}

// Only write to the bus if the CRC is valid, so garbage never reaches it
void send_command(unsigned char* buf, int len) {
  if (checkModbusCRC(buf, len)) {
    Serial1.write(buf, len);
    Serial.println(len);
  } else {
    Serial.println("crc error");
  }
}
