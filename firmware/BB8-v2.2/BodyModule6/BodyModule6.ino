// BB-8 Body v2 - ESP32 Arduino core 3.x; USB serial JSON bridge
#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
constexpr uint8_t CHANNEL=1;
constexpr uint32_t MAGIC=0x42384238;
constexpr uint8_t VERSION=2, TELEMETRY=1, COMMAND=2, ACK=3, LIGHT_COMMAND=4, LIGHT_ACK=5, SOUND_COMMAND=6, SOUND_ACK=7, HEADLAMP_COMMAND=8, HEADLAMP_ACK=9;
constexpr uint16_t FLAG_LIGHT=4, FLAG_ILLUMINATION=8, FLAG_LED_ON=16, FLAG_SOUND=32, FLAG_HEADLAMP=64;
constexpr uint16_t FLAG_VALID=1,FLAG_OBSTACLE=2;
enum Sound : uint8_t { HELLO, YES, NO, QUESTION, ACKNOWLEDGE, EXCITED, CONFUSED, WARNING, GOODBYE, SOUND_COUNT };
enum HeadlampMode : uint8_t { HEADLAMP_AUTO, HEADLAMP_OFF, HEADLAMP_STEADY, HEADLAMP_BREATHE, HEADLAMP_BLINK, HEADLAMP_MODE_COUNT };
constexpr uint32_t LINK_TIMEOUT_MS=500, REPORT_PERIOD_MS=100;
struct __attribute__((packed)) Packet {
  uint32_t magic;uint8_t version,type;uint16_t flags;
  uint32_t sequence,sample_age_ms;uint16_t distance_cm,strength;
  uint8_t mood,reserved[3];
};
static_assert(sizeof(Packet)==24,"Unexpected packet size");
portMUX_TYPE rxMux=portMUX_INITIALIZER_UNLOCKED;
Packet pendingTelemetry{},pendingAck{};
uint8_t pendingMac[6]{},pendingAckMac[6]{};
volatile bool telemetryPending=false,ackPending=false;
uint32_t dropped=0,lastReceive=0,lastReport=0,commandSequence=0;
uint32_t controllerSession=1;
Packet latest{};bool linked=false,paired=false,radioReady=false,hasTelemetry=false;
uint8_t headMac[6]{};
char line[96];uint8_t lineLength=0;bool overflow=false;
uint32_t lastSequence=0;bool haveSequence=false;
void onReceive(const esp_now_recv_info_t *info,const uint8_t *data,int len){
  if(!info || !info->src_addr || len!=(int)sizeof(Packet))return;
  Packet p;memcpy(&p,data,sizeof(p));
  if(p.magic!=MAGIC||p.version!=VERSION)return;
  portENTER_CRITICAL(&rxMux);
  if(p.type==TELEMETRY){
    if(telemetryPending)dropped++;
    pendingTelemetry=p;memcpy(pendingMac,info->src_addr,6);telemetryPending=true;
  }else if(p.type==ACK || p.type==LIGHT_ACK || p.type==SOUND_ACK || p.type==HEADLAMP_ACK){
    if((p.type==SOUND_ACK || p.type==HEADLAMP_ACK) && p.sample_age_ms!=controllerSession){portEXIT_CRITICAL(&rxMux);return;}
    pendingAck=p;memcpy(pendingAckMac,info->src_addr,6);ackPending=true;
  }
  portEXIT_CRITICAL(&rxMux);
}
int moodId(const char *s){
  if(!strcmp(s,"silent"))return 0;if(!strcmp(s,"happy"))return 1;
  if(!strcmp(s,"curious"))return 2;if(!strcmp(s,"talk"))return 3;
  if(!strcmp(s,"alarm"))return 4;if(!strcmp(s,"boot"))return 5;
  return -1;
}
int soundId(const char *s){
  static const char *names[]={"hello","yes","no","question","acknowledge","excited","confused","warning","goodbye"};
  for(int i=0;i<9;i++)if(!strcmp(s,names[i]))return i;
  return -1;
}
int headlampModeId(const char *s){
  static const char *names[]={"auto","off","steady","breathe","blink"};
  for(int i=0;i<HEADLAMP_MODE_COUNT;i++)if(!strcmp(s,names[i]))return i;
  return -1;
}
const char *headlampModeName(uint8_t mode){
  static const char *names[]={"auto","off","steady","breathe","blink"};
  return mode<HEADLAMP_MODE_COUNT?names[mode]:"invalid";
}
bool safeNumericTail(const char *s){
  uint8_t digits=0;
  for(;*s;s++){
    if(*s>='0'&&*s<='9'){if(++digits>4)return false;}
    else if(*s==' '||*s=='\t')digits=0;
    else return false;
  }
  return true;
}
void handleLine(char *s){
  // Exact commands: mood, sound, legacy illumination, or bounded headlamp primitives.
  while(*s==' '||*s=='\t')s++;
  int light=-1,sound=-1,headlamp=-1;
  unsigned red=0,green=0,blue=0,brightness=0,period=0,duration=0;int consumed=0;
  if(!strcmp(s,"illumination on"))light=1;
  if(!strcmp(s,"illumination off"))light=0;
  if(!strncmp(s,"sound ",6))sound=soundId(s+6);
  if(!strcmp(s,"headlamp auto"))headlamp=HEADLAMP_AUTO;
  else if(!strncmp(s,"headlamp off ",sizeof("headlamp off ")-1) && safeNumericTail(s+sizeof("headlamp off ")-1) && sscanf(s,"headlamp off %u %n",&duration,&consumed)==1 && s[consumed]==0 && duration>=1 && duration<=300)headlamp=HEADLAMP_OFF;
  else if(!strncmp(s,"headlamp steady ",sizeof("headlamp steady ")-1) && safeNumericTail(s+sizeof("headlamp steady ")-1) && sscanf(s,"headlamp steady %u %u %u %u %u %n",&red,&green,&blue,&brightness,&duration,&consumed)==5 && s[consumed]==0 &&
          red<=255 && green<=255 && blue<=255 && (red||green||blue) && brightness>=1 && brightness<=100 && duration>=1 && duration<=300)headlamp=HEADLAMP_STEADY;
  else {
    char mode[12]{};
    const char *numbers=!strncmp(s,"headlamp ",sizeof("headlamp ")-1)?strchr(s+sizeof("headlamp ")-1,' '):nullptr;
    if(numbers && safeNumericTail(numbers+1) && sscanf(s,"headlamp %11s %u %u %u %u %u %u %n",mode,&red,&green,&blue,&brightness,&period,&duration,&consumed)==7 && s[consumed]==0){
      int parsed=headlampModeId(mode);
      if((parsed==HEADLAMP_BREATHE || parsed==HEADLAMP_BLINK) && red<=255 && green<=255 && blue<=255 && (red||green||blue) &&
         brightness>=1 && brightness<=100 && period>=300 && period<=5000 && duration>=1 && duration<=300)headlamp=parsed;
    }
  }
  int mood=moodId(s);
  if(mood<0 && !strncmp(s,"mood ",5))mood=moodId(s+5);
  if(mood<0 && *s=='{'){
    const char *key=strstr(s,"\"mood\"");
    if(!key)key=strstr(s,"\"command\"");
    if(key){const char *colon=strchr(key,':');if(colon){const char *q=strchr(colon,'\"');if(q){char value[20]{};const char *end=strchr(q+1,'\"');if(end && end-q-1<sizeof(value)){memcpy(value,q+1,end-q-1);mood=moodId(value);}}}}
  }
  if(mood<0 && light<0 && sound<0 && headlamp<0){Serial.println("{\"type\":\"error\",\"error\":\"unknown_command\"}");return;}
  if(!radioReady||!paired){Serial.println("{\"type\":\"error\",\"error\":\"head_not_paired\"}");return;}
  if(light>=0 && (!linked || !(latest.flags&FLAG_ILLUMINATION))){Serial.println("{\"type\":\"error\",\"error\":\"illumination_unsupported\"}");return;}
  if(headlamp>=0 && (!linked || !(latest.flags&FLAG_HEADLAMP))){Serial.println("{\"type\":\"error\",\"error\":\"headlamp_unsupported\"}");return;}
  if(sound>=0 && (!linked || !(latest.flags&FLAG_SOUND))){Serial.println("{\"type\":\"error\",\"error\":\"sound_unsupported\"}");return;}
  if(sound>=0 && (latest.flags&FLAG_OBSTACLE)){Serial.println("{\"type\":\"error\",\"error\":\"sound_blocked_obstacle\"}");return;}
  Packet p{};p.magic=MAGIC;p.version=VERSION;
  p.type=headlamp>=0?HEADLAMP_COMMAND:(light>=0?LIGHT_COMMAND:(sound>=0?SOUND_COMMAND:COMMAND));p.sequence=++commandSequence;
  p.sample_age_ms=(sound>=0||headlamp>=0)?controllerSession:0;
  p.mood=(uint8_t)(headlamp>=0?headlamp:(sound>=0?sound:(mood>=0?mood:0)));
  if(light>=0)p.reserved[0]=(uint8_t)light;
  if(headlamp>=0){p.flags=(uint16_t)duration;p.distance_cm=(uint16_t)period;p.strength=(uint16_t)brightness;p.reserved[0]=(uint8_t)red;p.reserved[1]=(uint8_t)green;p.reserved[2]=(uint8_t)blue;}
  esp_err_t result=esp_now_send(headMac,(uint8_t*)&p,sizeof(p));
  Serial.printf("{\"type\":\"command_sent\",\"id\":%lu,\"accepted_by_radio\":%s}\n",(unsigned long)p.sequence,result==ESP_OK?"true":"false");
}
void setup(){
  Serial.begin(115200);controllerSession=esp_random();if(controllerSession==0)controllerSession=1;WiFi.mode(WIFI_STA);WiFi.setSleep(false);
  esp_err_t channel=esp_wifi_set_channel(CHANNEL,WIFI_SECOND_CHAN_NONE);
  if(channel==ESP_OK && esp_now_init()==ESP_OK){radioReady=true;esp_now_register_recv_cb(onReceive);}
  Serial.printf("{\"type\":\"system\",\"role\":\"Body_Bridge\",\"version\":2,\"radio_ready\":%s,\"mac\":\"%s\"}\n",radioReady?"true":"false",WiFi.macAddress().c_str());
}
void loop(){
  uint32_t now=millis();
  int budget=128;while(budget-- && Serial.available()){
    char c=(char)Serial.read();if(c=='\r')continue;
    if(c=='\n'){
      if(overflow)Serial.println("{\"type\":\"error\",\"error\":\"line_too_long\"}");
      else if(lineLength){line[lineLength]=0;handleLine(line);}
      lineLength=0;overflow=false;
    }else if(!overflow){if(lineLength<sizeof(line)-1)line[lineLength++]=c;else overflow=true;}
  }
  Packet p{},ack{};uint8_t src[6]{},ackSrc[6]{};bool got=false,gotAck=false;
  portENTER_CRITICAL(&rxMux);
  if(telemetryPending){p=pendingTelemetry;memcpy(src,pendingMac,6);telemetryPending=false;got=true;}
  if(ackPending){ack=pendingAck;memcpy(ackSrc,pendingAckMac,6);ackPending=false;gotAck=true;}
  portEXIT_CRITICAL(&rxMux);
  // A head reboot resets its sequence counter. After a link timeout,
  // forget the previous sequence so the next valid packet can establish
  // a fresh session without resetting the body.
  if(hasTelemetry && (uint32_t)(now-lastReceive)>LINK_TIMEOUT_MS){
    haveSequence=false;
    linked=false;
  }
  if(got){
    if(!paired){
      esp_now_peer_info_t peer{};memcpy(peer.peer_addr,src,6);peer.channel=CHANNEL;peer.encrypt=false;
      if(esp_now_add_peer(&peer)==ESP_OK || esp_now_is_peer_exist(src)){
        memcpy(headMac,src,6);paired=true;
        Serial.printf("{\"type\":\"system\",\"status\":\"head_paired\",\"mac\":\"%02X:%02X:%02X:%02X:%02X:%02X\"}\n",src[0],src[1],src[2],src[3],src[4],src[5]);
      }
    }
    if(paired && memcmp(src,headMac,6)==0){
      // Out-of-order packets must not replace newer data.
      if(!haveSequence || (int32_t)(p.sequence-lastSequence)>0){
        latest=p;lastSequence=p.sequence;haveSequence=true;lastReceive=now;linked=true;hasTelemetry=true;
      }
    }
  }
  if(gotAck && paired && memcmp(ackSrc,headMac,6)==0){
    if(ack.type==ACK && ack.mood<=5)Serial.printf("{\"type\":\"command_ack\",\"id\":%lu,\"mood\":%u}\n",(unsigned long)ack.sequence,ack.mood);
    else if(ack.type==LIGHT_ACK && ack.reserved[0]<=1)Serial.printf("{\"type\":\"illumination_ack\",\"id\":%lu,\"on\":%s}\n",(unsigned long)ack.sequence,ack.reserved[0]?"true":"false");
    else if(ack.type==SOUND_ACK && ack.mood<9)Serial.printf("{\"type\":\"sound_ack\",\"id\":%lu,\"sound\":%u}\n",(unsigned long)ack.sequence,ack.mood);
    else if(ack.type==HEADLAMP_ACK && ack.mood<HEADLAMP_MODE_COUNT)Serial.printf("{\"type\":\"headlamp_ack\",\"id\":%lu,\"mode\":\"%s\",\"red\":%u,\"green\":%u,\"blue\":%u,\"brightness_percent\":%u,\"period_ms\":%u,\"duration_s\":%u}\n",(unsigned long)ack.sequence,headlampModeName(ack.mood),ack.reserved[0],ack.reserved[1],ack.reserved[2],ack.strength,ack.distance_cm,ack.flags);
  }
  if((uint32_t)(now-lastReport)>=REPORT_PERIOD_MS){
    lastReport=now;
    linked=hasTelemetry && (uint32_t)(now-lastReceive)<=LINK_TIMEOUT_MS;
    uint32_t transportAge=hasTelemetry?(uint32_t)(now-lastReceive):UINT32_MAX;
    bool valid=linked && (latest.flags&FLAG_VALID) && latest.sample_age_ms!=UINT32_MAX && latest.sample_age_ms+transportAge<=350;
    bool brake=!valid || (latest.flags&FLAG_OBSTACLE);
    // dist/brake preserve RoboClaw's original fields. Null means unknown, never zero-distance fabrication.
    Serial.printf("{\"type\":\"telemetry\",\"dist\":");
    if(valid)Serial.print(latest.distance_cm);else Serial.print("null");
    Serial.printf(",\"brake\":%s,\"sensor_valid\":%s,\"head_connected\":%s,\"strength\":",brake?"true":"false",valid?"true":"false",linked?"true":"false");
    if(valid)Serial.print(latest.strength);else Serial.print("null");
    Serial.print(",\"sample_age_ms\":");
    if(valid)Serial.print(latest.sample_age_ms+transportAge);else Serial.print("null");
    Serial.printf(",\"seq\":%lu,\"rx_overwrites\":%lu",(unsigned long)latest.sequence,(unsigned long)dropped);
    bool lightSupported=linked && (latest.flags&FLAG_LIGHT);
    bool illuminationSupported=linked && (latest.flags&FLAG_ILLUMINATION);
    uint16_t raw=(uint16_t)latest.reserved[0]|((uint16_t)latest.reserved[1]<<8);
    Serial.printf(",\"light_supported\":%s,\"illumination_supported\":%s,\"light_raw\":",lightSupported?"true":"false",illuminationSupported?"true":"false");
    if(lightSupported && raw<=4095)Serial.print(raw);else Serial.print("null");
    Serial.print(",\"light_age_ms\":");if(lightSupported)Serial.print(transportAge);else Serial.print("null");
    Serial.print(",\"illumination_on\":");if(illuminationSupported)Serial.print((latest.flags&FLAG_LED_ON)?"true":"false");else Serial.print("null");
    Serial.printf(",\"sound_supported\":%s",linked && (latest.flags&FLAG_SOUND)?"true":"false");
    bool headlampSupported=linked && (latest.flags&FLAG_HEADLAMP) && latest.mood<HEADLAMP_MODE_COUNT && latest.reserved[2]<=64;
    Serial.printf(",\"headlamp_supported\":%s,\"headlamp_mode\":",headlampSupported?"true":"false");
    if(headlampSupported)Serial.printf("\"%s\"",headlampModeName(latest.mood));else Serial.print("null");
    Serial.print(",\"headlamp_level\":");if(headlampSupported)Serial.print((uint32_t)latest.reserved[2]);else Serial.print("null");
    Serial.println("}");
  }
}
