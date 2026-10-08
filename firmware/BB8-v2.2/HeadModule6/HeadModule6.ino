// BB-8 Head v2 - ESP32 Arduino core 3.x
#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
#include <HardwareSerial.h>

constexpr int BUZZER_PIN=4, TF_RX=17, TF_TX=18;
constexpr int LIGHT_PIN=1, ILLUMINATION_PIN=5;
constexpr bool ENABLE_LIGHT_SENSOR=true, ENABLE_ILLUMINATION=true;
static_assert(LIGHT_PIN!=BUZZER_PIN && LIGHT_PIN!=TF_RX && LIGHT_PIN!=TF_TX && LIGHT_PIN!=ILLUMINATION_PIN,"Pin conflict");
static_assert(ILLUMINATION_PIN!=BUZZER_PIN && ILLUMINATION_PIN!=TF_RX && ILLUMINATION_PIN!=TF_TX,"Pin conflict");
bool illuminationOn=false;
constexpr uint8_t CHANNEL=1;
constexpr uint32_t MAGIC=0x42384238; // B8B8
constexpr uint8_t VERSION=2, TELEMETRY=1, COMMAND=2, ACK=3, LIGHT_COMMAND=4, LIGHT_ACK=5;
constexpr uint16_t FLAG_LIGHT=4, FLAG_ILLUMINATION=8, FLAG_LED_ON=16;
constexpr uint32_t SAMPLE_TIMEOUT_MS=350, SEND_PERIOD_MS=50;
constexpr uint16_t BRAKE_ON_CM=30, BRAKE_OFF_CM=36, MIN_STRENGTH=100;
const uint8_t BROADCAST[6]={255,255,255,255,255,255};

struct __attribute__((packed)) Packet {
  uint32_t magic;
  uint8_t version, type;
  uint16_t flags;
  uint32_t sequence;
  uint32_t sample_age_ms;
  uint16_t distance_cm, strength;
  uint8_t mood, reserved[3];
};
static_assert(sizeof(Packet)==24,"Unexpected packet size");
constexpr uint16_t FLAG_VALID=1, FLAG_OBSTACLE=2;
enum Mood : uint8_t { SILENT, HAPPY, CURIOUS, TALK, ALARM, BOOT };
HardwareSerial lidar(1);
uint8_t frame[9]; uint8_t framePos=0;
uint16_t distanceCm=0, strength=0;
uint32_t lastGood=0, lastSend=0, sequence=0;
bool hasSample=false, obstacle=false, radioReady=false;
Mood mood=SILENT;
uint32_t toneAt=0; uint8_t step=0, talkSteps=0;
portMUX_TYPE commandMux=portMUX_INITIALIZER_UNLOCKED;
volatile bool commandPending=false;
Packet pendingCommand{};
uint8_t commandMac[6]{};
uint8_t lastController[6]{};
bool controllerKnown=false;

bool validPacket(const Packet &p){return p.magic==MAGIC && p.version==VERSION;}
void setTone(uint32_t hz){ledcWriteTone(BUZZER_PIN,hz);}
void startMood(Mood m){mood=m;step=0;toneAt=0;talkSteps=(uint8_t)random(10,18);setTone(0);}
void audioTick(uint32_t now){
  if(mood==SILENT)return;
  if(toneAt && (uint32_t)(now-toneAt)<((mood==TALK)?(step%2?45:25):(mood==BOOT?85:mood==CURIOUS?65:mood==ALARM?100:30)))return;
  toneAt=now;
  static const uint16_t boot[]={1046,1318,1568,2093};
  static const uint16_t curious[]={1150,1400,1320,1780,2100,2600,2450};
  const uint8_t count=mood==BOOT?4:mood==HAPPY?14:mood==CURIOUS?7:mood==ALARM?8:talkSteps;
  if(step>=count){setTone(0);mood=SILENT;return;}
  uint32_t hz=0;
  switch(mood){
    case BOOT:hz=boot[step];break;
    case HAPPY:hz=1000+step*115;break;
    case CURIOUS:hz=curious[step];break;
    case ALARM:hz=(step%2)?1850:3100;break;
    case TALK:hz=(step%2)?0:(uint32_t)random(900,2800);break;
    default:break;
  }
  setTone(hz);step++;
}
void ingest(uint8_t b,uint32_t now){
  if(framePos==0){if(b==0x59)frame[framePos++]=b;return;}
  if(framePos==1){if(b==0x59)frame[framePos++]=b;else framePos=(b==0x59)?1:0;return;}
  frame[framePos++]=b;
  if(framePos!=9)return;
  framePos=0;uint8_t sum=0;for(int i=0;i<8;i++)sum+=frame[i];
  if(sum!=frame[8])return;
  uint16_t d=(uint16_t)frame[2]|((uint16_t)frame[3]<<8);
  uint16_t s=(uint16_t)frame[4]|((uint16_t)frame[5]<<8);
  if(d==0 || s<MIN_STRENGTH)return;
  distanceCm=d;strength=s;lastGood=now;hasSample=true;
  if(!obstacle && d<BRAKE_ON_CM){obstacle=true;startMood(ALARM);}
  else if(obstacle && d>BRAKE_OFF_CM)obstacle=false;
}
void onReceive(const esp_now_recv_info_t *info,const uint8_t *data,int len){
  if(!info || !info->src_addr || len!=(int)sizeof(Packet))return;
  Packet p;memcpy(&p,data,sizeof(p));
  if(!validPacket(p))return;
  if(p.type==COMMAND){if(p.mood>BOOT)return;}
  else if(p.type==LIGHT_COMMAND){if(!ENABLE_ILLUMINATION || p.reserved[0]>1)return;}
  else return;
  portENTER_CRITICAL(&commandMux);
  pendingCommand=p;memcpy(commandMac,info->src_addr,6);commandPending=true;
  portEXIT_CRITICAL(&commandMux);
}
void setup(){
  Serial.begin(115200);randomSeed(esp_random());
  if(ENABLE_ILLUMINATION){digitalWrite(ILLUMINATION_PIN,LOW);pinMode(ILLUMINATION_PIN,OUTPUT);}
  if(ENABLE_LIGHT_SENSOR){pinMode(LIGHT_PIN,INPUT);analogReadResolution(12);analogSetPinAttenuation(LIGHT_PIN,ADC_11db);}
  ledcAttach(BUZZER_PIN,2000,8);startMood(BOOT);
  lidar.setRxBufferSize(512);lidar.begin(115200,SERIAL_8N1,TF_RX,TF_TX);
  WiFi.mode(WIFI_STA);WiFi.setSleep(false);
  if(esp_wifi_set_channel(CHANNEL,WIFI_SECOND_CHAN_NONE)!=ESP_OK)Serial.println("Head: channel error");
  if(esp_now_init()==ESP_OK){
    esp_now_peer_info_t peer{};memcpy(peer.peer_addr,BROADCAST,6);peer.channel=CHANNEL;peer.encrypt=false;
    radioReady=(esp_now_add_peer(&peer)==ESP_OK);
    if(radioReady)esp_now_register_recv_cb(onReceive);
  }
  Serial.printf("Head v2.2 MAC %s radio=%d\n",WiFi.macAddress().c_str(),radioReady);
}
void loop(){
  uint32_t now=millis();
  int budget=256;while(budget-- && lidar.available())ingest((uint8_t)lidar.read(),now);
  if(hasSample && (uint32_t)(now-lastGood)>SAMPLE_TIMEOUT_MS){hasSample=false;obstacle=false;}
  Packet cmd{};uint8_t src[6];bool got=false;
  portENTER_CRITICAL(&commandMux);
  if(commandPending){cmd=pendingCommand;memcpy(src,commandMac,6);commandPending=false;got=true;}
  portEXIT_CRITICAL(&commandMux);
  if(got){
    // Only accept commands from the first controller; reboot to change controller.
    if(!controllerKnown){memcpy(lastController,src,6);controllerKnown=true;}
    if(memcmp(src,lastController,6)==0){
      if(cmd.type==COMMAND)startMood((Mood)cmd.mood);
      else {illuminationOn=cmd.reserved[0]==1;digitalWrite(ILLUMINATION_PIN,illuminationOn?HIGH:LOW);}
      if(!esp_now_is_peer_exist(src)){
        esp_now_peer_info_t peer{};memcpy(peer.peer_addr,src,6);peer.channel=CHANNEL;peer.encrypt=false;
        esp_now_add_peer(&peer);
      }
      Packet ack{};ack.magic=MAGIC;ack.version=VERSION;ack.type=cmd.type==COMMAND?ACK:LIGHT_ACK;ack.reserved[0]=illuminationOn?1:0;ack.sequence=cmd.sequence;ack.mood=cmd.mood;
      esp_now_send(src,(uint8_t*)&ack,sizeof(ack));
    }
  }
  audioTick(now);
  if((uint32_t)(now-lastSend)>=SEND_PERIOD_MS){
    lastSend=now;
    Packet p{};p.magic=MAGIC;p.version=VERSION;p.type=TELEMETRY;p.sequence=++sequence;
    p.sample_age_ms=hasSample?now-lastGood:UINT32_MAX;
    p.flags=(hasSample?FLAG_VALID:0)|(hasSample&&obstacle?FLAG_OBSTACLE:0);
    p.distance_cm=hasSample?distanceCm:0;p.strength=hasSample?strength:0;
    if(ENABLE_LIGHT_SENSOR){
      uint32_t total=0;for(int i=0;i<8;i++)total+=analogRead(LIGHT_PIN);
      uint16_t raw=total/8;p.flags|=FLAG_LIGHT;p.reserved[0]=raw&255;p.reserved[1]=raw>>8;
    }
    if(ENABLE_ILLUMINATION)p.flags|=FLAG_ILLUMINATION;
    if(illuminationOn)p.flags|=FLAG_LED_ON;
    if(radioReady)esp_now_send(BROADCAST,(uint8_t*)&p,sizeof(p));
  }
}
