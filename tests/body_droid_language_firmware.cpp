#include <cassert>
#include "../firmware/BB8-v2.2/BodyModule6/BodyModule6.ino"

int main(){
  setup();
  uint8_t mac[6]={1,2,3,4,5,6};esp_now_recv_info_t info{mac};
  Packet telemetry{};telemetry.magic=MAGIC;telemetry.version=VERSION;telemetry.type=TELEMETRY;telemetry.sequence=1;telemetry.flags=FLAG_SOUND;
  fakeNow=100;onReceive(&info,(uint8_t*)&telemetry,sizeof(telemetry));loop();
  assert(Serial.output.find("\"sound_supported\":true")!=std::string::npos);

  char line[]="sound hello";handleLine(line);
  Packet cmd;memcpy(&cmd,sentPacket.data(),24);
  assert(cmd.type==SOUND_COMMAND);assert(cmd.mood==HELLO);assert(cmd.sample_age_ms==controllerSession);assert(controllerSession!=0);

  Packet ack{};ack.magic=MAGIC;ack.version=VERSION;ack.type=SOUND_ACK;ack.sample_age_ms=controllerSession;ack.sequence=cmd.sequence;ack.mood=HELLO;
  onReceive(&info,(uint8_t*)&ack,sizeof(ack));loop();
  assert(Serial.output.find("\"sound_ack\"")!=std::string::npos);
  assert(Serial.output.find("\"sound\":0")!=std::string::npos);
  Serial.output.clear();ack.sample_age_ms=controllerSession+1;onReceive(&info,(uint8_t*)&ack,sizeof(ack));loop();
  assert(Serial.output.find("sound_ack")==std::string::npos);

  latest.flags=0;Serial.output.clear();handleLine(line);
  assert(Serial.output.find("sound_unsupported")!=std::string::npos);

  latest.flags=FLAG_SOUND|FLAG_OBSTACLE;linked=true;Serial.output.clear();handleLine(line);
  assert(Serial.output.find("sound_blocked_obstacle")!=std::string::npos);
}
