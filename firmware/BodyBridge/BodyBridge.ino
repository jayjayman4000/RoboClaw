// Telemetry-only prototype. Arduino-ESP32 3.x; no actuator control.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "Protocol.h"

// REQUIRED: replace with your head's printed WiFi MAC. Zeroes reject every sender.
const uint8_t HEAD_MAC[6]={0,0,0,0,0,0};
struct Received { uint8_t packet[PACKET_SIZE]; uint32_t at; };
QueueHandle_t incoming=nullptr;
Received latest={};
bool seen=false;
uint32_t lastHello=0, lastOutput=0;
void receivePacket(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if(!incoming || !info || memcmp(info->src_addr,HEAD_MAC,6)!=0 ||
     len!=PACKET_SIZE || !packetValid(data,len)) return;
  Received value={}; memcpy(value.packet,data,PACKET_SIZE); value.at=millis();
  // ESP-NOW callback runs on a WiFi task; no serial I/O, pairing or control here.
  xQueueOverwrite(incoming,&value);
}
void hello() {
  String id=WiFi.macAddress();
  Serial.printf("{\"type\":\"hello\",\"protocol_version\":1,\"controller_id\":\"%s\",\"name\":\"BB8 body bridge\",\"firmware_version\":\"0.4.0-prototype\",\"capabilities\":[{\"id\":\"head_range\",\"kind\":\"sensor\",\"driver\":\"tfmini-plus\",\"units\":\"m\"}]}\n",id.c_str());
}
void setup() {
  Serial.begin(115200);
  incoming=xQueueCreate(1,sizeof(Received));
  WiFi.mode(WIFI_STA); WiFi.disconnect();
  if(!incoming || esp_wifi_set_channel(RADIO_CHANNEL,WIFI_SECOND_CHAN_NONE)!=ESP_OK || esp_now_init()!=ESP_OK) {
    Serial.println("{\"type\":\"system\",\"error\":\"radio initialization failed\"}"); return;
  }
  esp_now_register_recv_cb(receivePacket);
  hello();
}
void loop() {
  if(incoming && xQueueReceive(incoming,&latest,0)==pdTRUE) seen=true;
  uint32_t now=millis();
  if(uint32_t(now-lastHello)>=1000) {lastHello=now; hello();}
  if(uint32_t(now-lastOutput)<50) return;
  lastOutput=now;
  uint32_t residence=seen ? uint32_t(now-latest.at) : 0;
  uint64_t age=seen ? uint64_t(get32(latest.packet+8))+residence : 0;
  bool linkFresh=seen && residence<=1000;
  bool valid=linkFresh && latest.packet[3]==1 && age<=1000;
  uint16_t distance=get16(latest.packet+4), strength=get16(latest.packet+6);
  valid=valid && distance>0 && distance<=1200 && strength>=100 && strength!=65535;
  char distanceText[12], strengthText[12];
  if(valid) snprintf(distanceText,sizeof(distanceText),"%u",distance);
  else strcpy(distanceText,"null");
  if(seen) snprintf(strengthText,sizeof(strengthText),"%u",strength);
  else strcpy(strengthText,"null");
  Serial.printf("{\"type\":\"telemetry\",\"protocol_version\":1,\"distance_cm\":%s,\"strength\":%s,\"valid\":%s,\"sample_age_ms\":%llu,\"head_link_valid\":%s,\"sample_sequence\":%lu,\"brake\":%s}\n",
    distanceText,strengthText,valid?"true":"false",(unsigned long long)age,
    linkFresh?"true":"false",(unsigned long)get32(latest.packet+12),valid&&distance<30?"true":"false");
}
