#include <cassert>
#include "../firmware/BB8-v2.2/HeadModule6/HeadModule6.ino"
int main(){
 setup();
 assert(!illuminationOn);assert(autoLightingEnabled);assert(ringBrightness==0);
 assert(ILLUMINATION_PIN==5);assert(LED_COUNT==24);assert(ring.begun());assert(ring.getPin()==5);
 assert(ring.getPixelColor(0)==0);assert(ring.getPixelColor(23)==0);
 assert(autoBrightnessFor(3000,false)==0);
 assert(autoBrightnessFor(AUTO_ON_ADC+1,false)==0);
 assert(autoBrightnessFor(AUTO_ON_ADC,false)==AUTO_MIN_BRIGHTNESS);
 assert(autoBrightnessFor(1500,true)>AUTO_MIN_BRIGHTNESS);
 assert(autoBrightnessFor(AUTO_FULL_ADC,true)==AUTO_MAX_BRIGHTNESS);
 assert(autoBrightnessFor(2600,true)==AUTO_MIN_BRIGHTNESS);
 assert(autoBrightnessFor(AUTO_OFF_ADC,true)==0);

 adcValue=3000;fakeNow=50;loop();assert(!illuminationOn);assert(ringBrightness==0);
 adcValue=600;
 for(int i=0;i<40;i++){fakeNow+=50;loop();}
 assert(illuminationOn);assert(ringBrightness>50);assert(ring.getPixelColor(0)==ring.Color(255,255,255));
 Packet p;memcpy(&p,sentPacket.data(),24);assert(p.flags&FLAG_LIGHT);assert(p.flags&FLAG_ILLUMINATION);assert(p.flags&FLAG_LED_ON);
 assert(((unsigned)p.reserved[0]|((unsigned)p.reserved[1]<<8))==600);

 uint8_t mac[6]={1,2,3,4,5,6};esp_now_recv_info_t info{mac};
 Packet cmd{};cmd.magic=MAGIC;cmd.version=VERSION;cmd.type=LIGHT_COMMAND;cmd.sequence=7;cmd.reserved[0]=0;
 onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();assert(!autoLightingEnabled);assert(!illuminationOn);assert(ringBrightness==0);assert(ring.getPixelColor(0)==0);
 memcpy(&p,sentPacket.data(),24);assert(p.type==LIGHT_ACK);assert(p.sequence==7);assert(p.reserved[0]==0);
 fakeNow+=50;adcValue=0;loop();assert(!illuminationOn);assert(ringBrightness==0);
 cmd.reserved[0]=1;cmd.sequence=8;onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();assert(illuminationOn);assert(ringBrightness==AUTO_MAX_BRIGHTNESS);assert(ring.getPixelColor(0)==ring.Color(255,255,255));
 cmd.reserved[0]=2;onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));assert(!commandPending);
 cmd.reserved[0]=1;cmd.magic=0;onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));assert(!commandPending);

 Packet lamp{};lamp.magic=MAGIC;lamp.version=VERSION;lamp.type=HEADLAMP_COMMAND;
 lamp.sequence=9;lamp.sample_age_ms=123;lamp.mood=HEADLAMP_STEADY;lamp.flags=30;
 lamp.strength=40;lamp.reserved[0]=255;lamp.reserved[1]=0;lamp.reserved[2]=0;
 onReceive(&info,(uint8_t*)&lamp,sizeof(lamp));loop();
 assert(headlampMode==HEADLAMP_STEADY);assert(!autoLightingEnabled);assert(illuminationOn);
 assert(ringBrightness<=HEADLAMP_MAX_BRIGHTNESS);assert(ring.getPixelColor(0)==ring.Color(255,0,0));
 memcpy(&p,sentPacket.data(),24);assert(p.type==HEADLAMP_ACK);assert(p.sequence==9);
 assert(p.sample_age_ms==123);assert(p.mood==HEADLAMP_STEADY);assert(p.strength==40);assert(p.flags==30);
 uint32_t shows=ring.showCount(),packets=sentPacketCount;onReceive(&info,(uint8_t*)&lamp,sizeof(lamp));loop();assert(ring.showCount()==shows);assert(sentPacketCount==packets);

 fakeNow+=31000;loop();assert(headlampMode==HEADLAMP_AUTO);assert(autoLightingEnabled);
 lamp.sequence=10;lamp.mood=HEADLAMP_BREATHE;lamp.flags=30;lamp.distance_cm=2400;lamp.strength=50;
 lamp.reserved[0]=0;lamp.reserved[1]=0;lamp.reserved[2]=255;
 onReceive(&info,(uint8_t*)&lamp,sizeof(lamp));loop();uint8_t first=ringBrightness;
 fakeNow+=600;loop();assert(ringBrightness!=first);assert(ring.getPixelColor(0)==ring.Color(0,0,255));
 lamp.sequence=11;lamp.strength=101;onReceive(&info,(uint8_t*)&lamp,sizeof(lamp));assert(!commandPending);

 fakeNow=UINT32_MAX-1000;lamp.sequence=12;lamp.mood=HEADLAMP_OFF;lamp.flags=1;lamp.distance_cm=0;lamp.strength=0;
 lamp.reserved[0]=lamp.reserved[1]=lamp.reserved[2]=0;onReceive(&info,(uint8_t*)&lamp,sizeof(lamp));loop();assert(headlampMode==HEADLAMP_OFF);
 fakeNow+=1500;loop();assert(headlampMode==HEADLAMP_AUTO);
 lamp.sequence=13;lamp.mood=HEADLAMP_BLINK;lamp.flags=30;lamp.distance_cm=400;lamp.strength=50;lamp.reserved[0]=255;
 onReceive(&info,(uint8_t*)&lamp,sizeof(lamp));loop();assert(illuminationOn);
 fakeNow+=200;loop();assert(!illuminationOn);
}