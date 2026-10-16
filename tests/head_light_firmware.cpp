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
}