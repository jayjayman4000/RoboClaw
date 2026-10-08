#include <cassert>
#include "../firmware/BB8-v2.2/BodyModule6/BodyModule6.ino"
int main(){
 setup();uint8_t mac[6]={1,2,3,4,5,6};esp_now_recv_info_t info{mac};
 Packet p{};p.magic=MAGIC;p.version=VERSION;p.type=TELEMETRY;p.sequence=1;p.flags=FLAG_LIGHT|FLAG_ILLUMINATION;
 p.reserved[0]=0;p.reserved[1]=8;fakeNow=100;onReceive(&info,(uint8_t*)&p,24);loop();
 assert(Serial.output.find("\"light_raw\":2048")!=std::string::npos);assert(Serial.output.find("\"illumination_on\":false")!=std::string::npos);
 char command[]="illumination on";handleLine(command);Packet cmd;memcpy(&cmd,sentPacket.data(),24);
 assert(cmd.type==LIGHT_COMMAND);assert(cmd.reserved[0]==1);
 Packet ack{};ack.magic=MAGIC;ack.version=VERSION;ack.type=LIGHT_ACK;ack.sequence=cmd.sequence;ack.reserved[0]=1;
 onReceive(&info,(uint8_t*)&ack,24);loop();assert(Serial.output.find("\"illumination_ack\"")!=std::string::npos);
 Serial.output.clear();uint8_t stranger[6]={9,9,9,9,9,9};esp_now_recv_info_t other{stranger};
 onReceive(&other,(uint8_t*)&ack,24);loop();assert(Serial.output.find("illumination_ack")==std::string::npos);
 latest.flags=0;Serial.output.clear();handleLine(command);assert(Serial.output.find("illumination_unsupported")!=std::string::npos);
 fakeNow=700;loop();assert(!linked);
}
