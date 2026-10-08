// Telemetry-only prototype. Arduino-ESP32 3.x; no motor/audio/LED commands.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "Protocol.h"

static const int TF_RX=17, TF_TX=18; // Verify against your board before wiring.
HardwareSerial tfSerial(1);
TfParser parser;
uint8_t broadcastMac[6]={255,255,255,255,255,255};
bool radioReady=false, seen=false;
uint32_t sampleTime=0, lastSend=0, sequence=0;

void setup() {
  Serial.begin(115200);
  tfSerial.begin(115200, SERIAL_8N1, TF_RX, TF_TX);
  WiFi.mode(WIFI_STA); WiFi.disconnect();
  if(esp_wifi_set_channel(RADIO_CHANNEL,WIFI_SECOND_CHAN_NONE)!=ESP_OK || esp_now_init()!=ESP_OK) {
    Serial.println("Radio initialization failed"); return;
  }
  esp_now_peer_info_t peer={};
  memcpy(peer.peer_addr,broadcastMac,6); peer.channel=RADIO_CHANNEL; peer.encrypt=false;
  radioReady=esp_now_add_peer(&peer)==ESP_OK;
  Serial.print("Head MAC: "); Serial.println(WiFi.macAddress());
}
void loop() {
  // Bound work per loop; parser never blocks on an incomplete UART frame.
  for(int count=0; count<256 && tfSerial.available(); count++) {
    if(parser.feed(uint8_t(tfSerial.read()))) {seen=true; sampleTime=millis(); ++sequence;}
  }
  uint32_t now=millis();
  if(radioReady && uint32_t(now-lastSend)>=50) {
    lastSend=now;
    uint8_t packet[PACKET_SIZE]={}; packet[0]='R'; packet[1]='C'; packet[2]=1;
    uint32_t age=seen ? uint32_t(now-sampleTime) : 0;
    packet[3]=seen && parser.valid && age<=1000;
    put16(packet+4,parser.distance); put16(packet+6,parser.strength);
    put32(packet+8,age); put32(packet+12,sequence);
    // Packet bytes 16..19 reserved, must remain zero.
    esp_now_send(broadcastMac,packet,sizeof(packet));
  }
}
