#include <cassert>
#include "../firmware/BB8-v2.2/BodyModule6/BodyModule6.ino"
int main(){
 setup();uint8_t mac[6]={1,2,3,4,5,6};esp_now_recv_info_t info{mac};
 Packet p{};p.magic=MAGIC;p.version=VERSION;p.type=TELEMETRY;p.sequence=1;p.flags=FLAG_LIGHT|FLAG_ILLUMINATION|FLAG_HEADLAMP;
 p.reserved[0]=0;p.reserved[1]=8;p.reserved[2]=0;p.mood=HEADLAMP_AUTO;fakeNow=100;onReceive(&info,(uint8_t*)&p,24);loop();
 assert(Serial.output.find("\"light_raw\":2048")!=std::string::npos);assert(Serial.output.find("\"illumination_on\":false")!=std::string::npos);
 assert(Serial.output.find("\"headlamp_supported\":true")!=std::string::npos);assert(Serial.output.find("\"headlamp_mode\":\"auto\"")!=std::string::npos);
 char command[]="illumination on";handleLine(command);Packet cmd;memcpy(&cmd,sentPacket.data(),24);
 assert(cmd.type==LIGHT_COMMAND);assert(cmd.reserved[0]==1);
 Packet ack{};ack.magic=MAGIC;ack.version=VERSION;ack.type=LIGHT_ACK;ack.sequence=cmd.sequence;ack.reserved[0]=1;
 onReceive(&info,(uint8_t*)&ack,24);loop();assert(Serial.output.find("\"illumination_ack\"")!=std::string::npos);
 Serial.output.clear();uint8_t stranger[6]={9,9,9,9,9,9};esp_now_recv_info_t other{stranger};
 onReceive(&other,(uint8_t*)&ack,24);loop();assert(Serial.output.find("illumination_ack")==std::string::npos);
 latest.flags=0;Serial.output.clear();handleLine(command);assert(Serial.output.find("illumination_unsupported")!=std::string::npos);
 latest.flags=FLAG_HEADLAMP;Serial.output.clear();char lampLine[]="headlamp steady 255 0 0 40 30";handleLine(lampLine);memcpy(&cmd,sentPacket.data(),24);
 assert(cmd.type==HEADLAMP_COMMAND);assert(cmd.mood==HEADLAMP_STEADY);assert(cmd.sample_age_ms==controllerSession);
 assert(cmd.reserved[0]==255&&cmd.reserved[1]==0&&cmd.reserved[2]==0);assert(cmd.strength==40);assert(cmd.flags==30);
 Packet lampAck=cmd;lampAck.type=HEADLAMP_ACK;onReceive(&info,(uint8_t*)&lampAck,24);loop();
 assert(Serial.output.find("\"headlamp_ack\"")!=std::string::npos);assert(Serial.output.find("\"brightness_percent\":40")!=std::string::npos);
 Serial.output.clear();char invalidLamp[]="headlamp blink 0 0 255 100 200 30";handleLine(invalidLamp);assert(Serial.output.find("unknown_command")!=std::string::npos);
 Serial.output.clear();char overflowLamp[]="headlamp off 4294967297";handleLine(overflowLamp);assert(Serial.output.find("unknown_command")!=std::string::npos);
 fakeNow=700;loop();assert(!linked);
}
