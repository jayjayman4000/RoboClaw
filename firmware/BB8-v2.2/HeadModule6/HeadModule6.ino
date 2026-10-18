// BB-8 Head v2 - ESP32 Arduino core 3.x
#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
#include <HardwareSerial.h>
#include <Adafruit_NeoPixel.h>

constexpr int BUZZER_PIN=4, TF_RX=17, TF_TX=18;
constexpr int LIGHT_PIN=1, ILLUMINATION_PIN=5;
constexpr uint16_t LED_COUNT=24;
constexpr uint16_t AUTO_FULL_ADC=600, AUTO_ON_ADC=2400, AUTO_OFF_ADC=2700;
constexpr uint8_t AUTO_MIN_BRIGHTNESS=8, AUTO_MAX_BRIGHTNESS=64;
constexpr uint8_t HEADLAMP_MAX_BRIGHTNESS=64;
constexpr bool ENABLE_LIGHT_SENSOR=true, ENABLE_ILLUMINATION=true;
static_assert(LIGHT_PIN!=BUZZER_PIN && LIGHT_PIN!=TF_RX && LIGHT_PIN!=TF_TX && LIGHT_PIN!=ILLUMINATION_PIN,"Pin conflict");
static_assert(ILLUMINATION_PIN!=BUZZER_PIN && ILLUMINATION_PIN!=TF_RX && ILLUMINATION_PIN!=TF_TX,"Pin conflict");
static_assert(AUTO_FULL_ADC<AUTO_ON_ADC && AUTO_ON_ADC<AUTO_OFF_ADC,"Invalid light thresholds");
static_assert(AUTO_MIN_BRIGHTNESS>0 && AUTO_MIN_BRIGHTNESS<AUTO_MAX_BRIGHTNESS,"Invalid brightness range");
Adafruit_NeoPixel ring(LED_COUNT,ILLUMINATION_PIN,NEO_GRB+NEO_KHZ800);
bool illuminationOn=false,autoLightingEnabled=true,ringOutputInitialized=false,filteredLightReady=false;
uint8_t ringBrightness=0,ringRed=0,ringGreen=0,ringBlue=0;
uint16_t filteredLight=0;
constexpr uint8_t CHANNEL=1;
constexpr uint32_t MAGIC=0x42384238; // B8B8
constexpr uint8_t VERSION=2, TELEMETRY=1, COMMAND=2, ACK=3, LIGHT_COMMAND=4, LIGHT_ACK=5, SOUND_COMMAND=6, SOUND_ACK=7, HEADLAMP_COMMAND=8, HEADLAMP_ACK=9;
constexpr uint16_t FLAG_LIGHT=4, FLAG_ILLUMINATION=8, FLAG_LED_ON=16, FLAG_SOUND=32, FLAG_HEADLAMP=64;
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
enum Sound : uint8_t { HELLO, YES, NO, QUESTION, ACKNOWLEDGE, EXCITED, CONFUSED, WARNING, GOODBYE, SOUND_COUNT };
enum HeadlampMode : uint8_t { HEADLAMP_AUTO, HEADLAMP_OFF, HEADLAMP_STEADY, HEADLAMP_BREATHE, HEADLAMP_BLINK, HEADLAMP_MODE_COUNT };
struct ToneStep { uint16_t hz, durationMs; };
constexpr ToneStep SOUND_HELLO[]={{1200,80},{0,35},{1700,90},{0,35},{2200,130}};
constexpr ToneStep SOUND_YES[]={{1500,80},{0,35},{2200,170}};
constexpr ToneStep SOUND_NO[]={{2200,90},{0,40},{1200,190}};
constexpr ToneStep SOUND_QUESTION[]={{1200,70},{0,30},{1600,70},{0,30},{2400,200}};
constexpr ToneStep SOUND_ACKNOWLEDGE[]={{1800,60},{0,25},{1800,60}};
constexpr ToneStep SOUND_EXCITED[]={{1500,55},{0,20},{1900,55},{0,20},{2400,70},{0,25},{2800,120}};
constexpr ToneStep SOUND_CONFUSED[]={{2100,90},{0,35},{1500,100},{0,70},{1850,160}};
constexpr ToneStep SOUND_WARNING[]={{2800,120},{0,60},{1700,120},{0,60},{2800,120},{0,60},{1700,160}};
constexpr ToneStep SOUND_GOODBYE[]={{2200,90},{0,40},{1700,100},{0,40},{1100,180}};
HardwareSerial lidar(1);
uint8_t frame[9]; uint8_t framePos=0;
uint16_t distanceCm=0, strength=0;
uint32_t lastGood=0, lastSend=0, sequence=0;
bool hasSample=false, obstacle=false, radioReady=false;
Mood mood=SILENT;
uint32_t toneAt=0; uint8_t step=0, talkSteps=0;
bool soundActive=false,soundStepRunning=false;Sound sound=HELLO;uint8_t soundStep=0;uint32_t soundToneAt=0;
portMUX_TYPE commandMux=portMUX_INITIALIZER_UNLOCKED;
volatile bool commandPending=false;
Packet pendingCommand{};
uint8_t commandMac[6]{};
uint8_t lastController[6]{};
bool controllerKnown=false;
uint32_t soundSession=0,lastSoundSequence=0,retiredSoundSessions[4]{};uint8_t retiredSoundSessionAt=0;bool haveSoundSession=false,haveSoundSequence=false;
HeadlampMode headlampMode=HEADLAMP_AUTO;
uint8_t headlampRed=255,headlampGreen=255,headlampBlue=255,headlampBrightnessPercent=0;
uint16_t headlampPeriodMs=0,headlampDurationS=0;
uint32_t headlampStartedAt=0,headlampExpiresAt=0;
bool headlampHasLease=false;
char usbLine[128]{};uint8_t usbLinePos=0;uint32_t directCommandId=0,directTelemetrySequence=0,lastDirectTelemetry=0;

bool validPacket(const Packet &p){return p.magic==MAGIC && p.version==VERSION;}
void setRingOutput(uint8_t brightness,uint8_t red,uint8_t green,uint8_t blue){
  if(brightness>HEADLAMP_MAX_BRIGHTNESS)brightness=HEADLAMP_MAX_BRIGHTNESS;
  if(ringOutputInitialized && brightness==ringBrightness && red==ringRed && green==ringGreen && blue==ringBlue)return;
  ringBrightness=brightness;illuminationOn=brightness>0;
  ringRed=red;ringGreen=green;ringBlue=blue;
  if(illuminationOn){ring.setBrightness(brightness);ring.fill(ring.Color(red,green,blue));}
  else ring.clear();
  ring.show();ringOutputInitialized=true;
}
void setIlluminationLevel(uint8_t brightness){setRingOutput(brightness,255,255,255);}
uint8_t autoBrightnessFor(uint16_t raw,bool currentlyOn){
  if(currentlyOn){if(raw>=AUTO_OFF_ADC)return 0;}
  else if(raw>AUTO_ON_ADC)return 0;
  if(raw>=AUTO_ON_ADC)return AUTO_MIN_BRIGHTNESS;
  if(raw<=AUTO_FULL_ADC)return AUTO_MAX_BRIGHTNESS;
  uint32_t darkness=AUTO_ON_ADC-raw;
  uint32_t span=AUTO_ON_ADC-AUTO_FULL_ADC;
  return AUTO_MIN_BRIGHTNESS+(uint8_t)((darkness*(AUTO_MAX_BRIGHTNESS-AUTO_MIN_BRIGHTNESS))/span);
}
void updateAutoIllumination(uint16_t raw){
  if(!autoLightingEnabled)return;
  if(!filteredLightReady){filteredLight=raw;filteredLightReady=true;}
  else filteredLight=(uint16_t)(((uint32_t)filteredLight*7+raw+4)/8);
  uint8_t target=autoBrightnessFor(filteredLight,illuminationOn);
  int delta=(int)target-(int)ringBrightness;if(delta<0)delta=-delta;
  if(target==0 || ringBrightness==0 || delta>=2)setIlluminationLevel(target);
}
bool validHeadlampCommand(const Packet &p){
  if(p.mood>=HEADLAMP_MODE_COUNT)return false;
  bool color=p.reserved[0]||p.reserved[1]||p.reserved[2];
  if(p.mood==HEADLAMP_AUTO)return p.flags==0 && p.distance_cm==0 && p.strength==0 && !color;
  if(p.flags<1 || p.flags>300)return false;
  if(p.mood==HEADLAMP_OFF)return p.distance_cm==0 && p.strength==0 && !color;
  if(!color || p.strength<1 || p.strength>100)return false;
  if(p.mood==HEADLAMP_STEADY)return p.distance_cm==0;
  return p.distance_cm>=300 && p.distance_cm<=5000;
}
bool acceptControllerSequence(uint32_t session,uint32_t sequence){
  if(session==0)return false;
  if(!haveSoundSession || session!=soundSession){
    for(uint8_t i=0;i<4;i++)if(retiredSoundSessions[i]==session)return false;
    if(haveSoundSession){retiredSoundSessions[retiredSoundSessionAt]=soundSession;retiredSoundSessionAt=(retiredSoundSessionAt+1)%4;}
    soundSession=session;haveSoundSession=true;haveSoundSequence=false;
  }
  if(haveSoundSequence && (int32_t)(sequence-lastSoundSequence)<=0)return false;
  lastSoundSequence=sequence;haveSoundSequence=true;return true;
}
void startHeadlamp(HeadlampMode mode,uint8_t red,uint8_t green,uint8_t blue,uint8_t brightnessPercent,uint16_t periodMs,uint16_t durationS,uint32_t now){
  headlampMode=mode;headlampRed=red;headlampGreen=green;headlampBlue=blue;
  headlampBrightnessPercent=brightnessPercent;headlampPeriodMs=periodMs;headlampDurationS=durationS;headlampStartedAt=now;
  autoLightingEnabled=mode==HEADLAMP_AUTO;headlampHasLease=mode!=HEADLAMP_AUTO && durationS>0;
  headlampExpiresAt=now+(uint32_t)durationS*1000;
  if(mode==HEADLAMP_AUTO){filteredLightReady=false;setIlluminationLevel(0);}
  else if(mode==HEADLAMP_OFF)setRingOutput(0,0,0,0);
}
void headlampTick(uint32_t now){
  if(headlampHasLease && (int32_t)(now-headlampExpiresAt)>=0){
    startHeadlamp(HEADLAMP_AUTO,0,0,0,0,0,0,now);return;
  }
  if(headlampMode==HEADLAMP_AUTO || headlampMode==HEADLAMP_OFF)return;
  uint8_t level=(uint8_t)(((uint16_t)headlampBrightnessPercent*HEADLAMP_MAX_BRIGHTNESS+99)/100);
  if(headlampMode==HEADLAMP_BREATHE){
    uint32_t phase=(now-headlampStartedAt)%headlampPeriodMs;
    uint32_t half=headlampPeriodMs/2;
    uint32_t wave=phase<=half?phase:headlampPeriodMs-phase;
    level=(uint8_t)((uint32_t)level*wave/(half?half:1));
  }else if(headlampMode==HEADLAMP_BLINK && ((now-headlampStartedAt)%headlampPeriodMs)>=headlampPeriodMs/2)level=0;
  setRingOutput(level,headlampRed,headlampGreen,headlampBlue);
}
const char *headlampModeName(HeadlampMode mode){
  static const char *names[]={"auto","off","steady","breathe","blink"};
  return mode<HEADLAMP_MODE_COUNT?names[mode]:"invalid";
}
void skipSpaces(const char *&p){while(*p==' '||*p=='\t')p++;}
bool parseUnsigned(const char *&p,uint32_t limit,uint32_t &value){
  skipSpaces(p);if(*p<'0'||*p>'9')return false;value=0;
  while(*p>='0'&&*p<='9'){
    uint8_t digit=(uint8_t)(*p-'0');if(value>(limit-digit)/10)return false;
    value=value*10+digit;p++;
  }
  if(*p && *p!=' ' && *p!='\t')return false;return true;
}
bool parseValues(const char *p,uint32_t *values,const uint32_t *limits,uint8_t count){
  for(uint8_t i=0;i<count;i++)if(!parseUnsigned(p,limits[i],values[i]))return false;
  skipSpaces(p);return *p==0;
}
void directHeadlampAck(uint32_t id){
  Serial.printf("{\"type\":\"headlamp_ack\",\"id\":%lu,\"mode\":\"%s\",\"red\":%u,\"green\":%u,\"blue\":%u,\"brightness_percent\":%u,\"period_ms\":%u,\"duration_s\":%u}\n",
                (unsigned long)id,headlampModeName(headlampMode),headlampRed,headlampGreen,headlampBlue,
                headlampBrightnessPercent,headlampPeriodMs,headlampDurationS);
}
void handleDirectHeadlamp(const char *line,uint32_t now){
  if(strncmp(line,"headlamp ",9)!=0){Serial.println("{\"type\":\"error\",\"error\":\"unsupported direct USB command\"}");return;}
  const char *request=line+9;HeadlampMode mode=HEADLAMP_AUTO;uint32_t value[6]{};
  uint32_t red=0,green=0,blue=0,brightness=0,period=0,duration=0;
  bool valid=false;
  if(!strcmp(request,"auto")){valid=true;}
  else if(!strncmp(request,"off ",4)){
    const uint32_t limits[]={300};valid=parseValues(request+4,value,limits,1)&&value[0]>=1;mode=HEADLAMP_OFF;duration=value[0];
  }else if(!strncmp(request,"steady ",7)){
    const uint32_t limits[]={255,255,255,100,300};valid=parseValues(request+7,value,limits,5);
    mode=HEADLAMP_STEADY;red=value[0];green=value[1];blue=value[2];brightness=value[3];duration=value[4];
    valid=valid&&(red||green||blue)&&brightness>=1&&duration>=1;
  }else{
    const char *numbers=nullptr;
    if(!strncmp(request,"breathe ",8)){mode=HEADLAMP_BREATHE;numbers=request+8;}
    else if(!strncmp(request,"blink ",6)){mode=HEADLAMP_BLINK;numbers=request+6;}
    if(numbers){
      const uint32_t limits[]={255,255,255,100,5000,300};valid=parseValues(numbers,value,limits,6);
      red=value[0];green=value[1];blue=value[2];brightness=value[3];period=value[4];duration=value[5];
      valid=valid&&(red||green||blue)&&brightness>=1&&period>=300&&duration>=1;
    }
  }
  if(!valid){Serial.println("{\"type\":\"error\",\"error\":\"invalid bounded headlamp command\"}");return;}
  uint32_t id=++directCommandId;
  Serial.printf("{\"type\":\"command_sent\",\"id\":%lu,\"accepted_by_radio\":true,\"transport\":\"direct_usb\"}\n",(unsigned long)id);
  startHeadlamp(mode,(uint8_t)red,(uint8_t)green,(uint8_t)blue,(uint8_t)brightness,(uint16_t)period,(uint16_t)duration,now);
  directHeadlampAck(id);
}
void directUsbTick(uint32_t now){
  uint8_t budget=96;
  while(budget-- && Serial.available()){
    int raw=Serial.read();if(raw<0)break;char c=(char)raw;
    if(c=='\r')continue;
    if(c=='\n'){
      usbLine[usbLinePos]=0;if(usbLinePos)handleDirectHeadlamp(usbLine,now);usbLinePos=0;continue;
    }
    if(usbLinePos<sizeof(usbLine)-1)usbLine[usbLinePos++]=c;
    else {usbLinePos=0;Serial.println("{\"type\":\"error\",\"error\":\"direct USB command too long\"}");}
  }
  if((uint32_t)(now-lastDirectTelemetry)>=200){
    lastDirectTelemetry=now;
    char line[256];int count=snprintf(line,sizeof(line),
      "{\"type\":\"telemetry\",\"dist\":null,\"sensor_valid\":false,\"head_connected\":true,\"sample_age_ms\":null,\"seq\":%lu,\"rx_overwrites\":0,\"headlamp_supported\":true,\"headlamp_mode\":\"%s\",\"headlamp_level\":%u}\n",
      (unsigned long)++directTelemetrySequence,headlampModeName(headlampMode),ringBrightness);
    if(count>0 && count<(int)sizeof(line) && Serial.availableForWrite()>=count)Serial.write((const uint8_t*)line,(size_t)count);
  }
}
void setTone(uint32_t hz){ledcWriteTone(BUZZER_PIN,hz);}
void startMood(Mood m){soundActive=false;soundStepRunning=false;mood=m;step=0;toneAt=0;talkSteps=(uint8_t)random(10,18);setTone(0);}
void soundPattern(Sound id,const ToneStep *&pattern,uint8_t &count){
  switch(id){
    case HELLO:pattern=SOUND_HELLO;count=sizeof(SOUND_HELLO)/sizeof(*SOUND_HELLO);break;
    case YES:pattern=SOUND_YES;count=sizeof(SOUND_YES)/sizeof(*SOUND_YES);break;
    case NO:pattern=SOUND_NO;count=sizeof(SOUND_NO)/sizeof(*SOUND_NO);break;
    case QUESTION:pattern=SOUND_QUESTION;count=sizeof(SOUND_QUESTION)/sizeof(*SOUND_QUESTION);break;
    case ACKNOWLEDGE:pattern=SOUND_ACKNOWLEDGE;count=sizeof(SOUND_ACKNOWLEDGE)/sizeof(*SOUND_ACKNOWLEDGE);break;
    case EXCITED:pattern=SOUND_EXCITED;count=sizeof(SOUND_EXCITED)/sizeof(*SOUND_EXCITED);break;
    case CONFUSED:pattern=SOUND_CONFUSED;count=sizeof(SOUND_CONFUSED)/sizeof(*SOUND_CONFUSED);break;
    case WARNING:pattern=SOUND_WARNING;count=sizeof(SOUND_WARNING)/sizeof(*SOUND_WARNING);break;
    case GOODBYE:pattern=SOUND_GOODBYE;count=sizeof(SOUND_GOODBYE)/sizeof(*SOUND_GOODBYE);break;
    default:pattern=nullptr;count=0;break;
  }
}
void startSound(Sound id){mood=SILENT;sound=id;soundStep=0;soundToneAt=0;soundStepRunning=false;soundActive=true;setTone(0);}
void audioTick(uint32_t now){
  if(soundActive){
    const ToneStep *pattern=nullptr;uint8_t count=0;soundPattern(sound,pattern,count);
    if(!pattern || soundStep>=count){setTone(0);soundActive=false;soundStepRunning=false;return;}
    if(!soundStepRunning){setTone(pattern[soundStep].hz);soundToneAt=now;soundStepRunning=true;return;}
    if((uint32_t)(now-soundToneAt)<pattern[soundStep].durationMs)return;
    soundStep++;soundStepRunning=false;
    if(soundStep>=count){setTone(0);soundActive=false;return;}
    setTone(pattern[soundStep].hz);soundToneAt=now;soundStepRunning=true;return;
  }
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
  else if(p.type==SOUND_COMMAND){if(p.mood>=SOUND_COUNT)return;}
  else if(p.type==LIGHT_COMMAND){if(!ENABLE_ILLUMINATION || p.reserved[0]>1)return;}
  else if(p.type==HEADLAMP_COMMAND){if(!ENABLE_ILLUMINATION || !validHeadlampCommand(p))return;}
  else return;
  portENTER_CRITICAL(&commandMux);
  pendingCommand=p;memcpy(commandMac,info->src_addr,6);commandPending=true;
  portEXIT_CRITICAL(&commandMux);
}
void setup(){
  Serial.begin(115200);randomSeed(esp_random());
  if(ENABLE_ILLUMINATION){ring.begin();setIlluminationLevel(0);}
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
      bool fresh=(cmd.type!=SOUND_COMMAND && cmd.type!=HEADLAMP_COMMAND) || acceptControllerSequence(cmd.sample_age_ms,cmd.sequence);
      if(fresh){
        bool accepted=true;
        if((cmd.type==COMMAND || cmd.type==SOUND_COMMAND) && obstacle)accepted=false;
        else if(cmd.type==COMMAND)startMood((Mood)cmd.mood);
        else if(cmd.type==SOUND_COMMAND)startSound((Sound)cmd.mood);
        else if(cmd.type==LIGHT_COMMAND){
          autoLightingEnabled=false;headlampMode=cmd.reserved[0]?HEADLAMP_STEADY:HEADLAMP_OFF;headlampHasLease=false;
          headlampRed=255;headlampGreen=255;headlampBlue=255;headlampBrightnessPercent=cmd.reserved[0]?100:0;headlampPeriodMs=0;
          setIlluminationLevel(cmd.reserved[0]==1?AUTO_MAX_BRIGHTNESS:0);
        }else startHeadlamp((HeadlampMode)cmd.mood,cmd.reserved[0],cmd.reserved[1],cmd.reserved[2],(uint8_t)cmd.strength,cmd.distance_cm,cmd.flags,now);
        if(accepted){
          if(!esp_now_is_peer_exist(src)){
            esp_now_peer_info_t peer{};memcpy(peer.peer_addr,src,6);peer.channel=CHANNEL;peer.encrypt=false;
            esp_now_add_peer(&peer);
          }
          Packet ack{};ack.magic=MAGIC;ack.version=VERSION;
          ack.type=cmd.type==COMMAND?ACK:(cmd.type==SOUND_COMMAND?SOUND_ACK:(cmd.type==HEADLAMP_COMMAND?HEADLAMP_ACK:LIGHT_ACK));
          ack.sequence=cmd.sequence;ack.mood=cmd.mood;
          if(cmd.type==HEADLAMP_COMMAND){ack.flags=cmd.flags;ack.sample_age_ms=cmd.sample_age_ms;ack.distance_cm=cmd.distance_cm;ack.strength=cmd.strength;memcpy(ack.reserved,cmd.reserved,3);}
          else {ack.reserved[0]=illuminationOn?1:0;ack.sample_age_ms=cmd.type==SOUND_COMMAND?cmd.sample_age_ms:0;}
          esp_now_send(src,(uint8_t*)&ack,sizeof(ack));
        }
      }
    }
  }
  audioTick(now);
  directUsbTick(now);
  headlampTick(now);
  if((uint32_t)(now-lastSend)>=SEND_PERIOD_MS){
    lastSend=now;
    Packet p{};p.magic=MAGIC;p.version=VERSION;p.type=TELEMETRY;p.sequence=++sequence;
    p.sample_age_ms=hasSample?now-lastGood:UINT32_MAX;
    p.flags=(hasSample?FLAG_VALID:0)|(hasSample&&obstacle?FLAG_OBSTACLE:0);
    p.distance_cm=hasSample?distanceCm:0;p.strength=hasSample?strength:0;
    if(ENABLE_LIGHT_SENSOR){
      uint32_t total=0;for(int i=0;i<8;i++)total+=analogRead(LIGHT_PIN);
      uint16_t raw=total/8;updateAutoIllumination(raw);p.flags|=FLAG_LIGHT;p.reserved[0]=raw&255;p.reserved[1]=raw>>8;
    }
    if(ENABLE_ILLUMINATION){p.flags|=FLAG_ILLUMINATION|FLAG_HEADLAMP;p.mood=(uint8_t)headlampMode;p.reserved[2]=ringBrightness;}
    p.flags|=FLAG_SOUND;
    if(illuminationOn)p.flags|=FLAG_LED_ON;
    if(radioReady)esp_now_send(BROADCAST,(uint8_t*)&p,sizeof(p));
  }
}
