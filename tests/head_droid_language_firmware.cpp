#include <cassert>
#include "../firmware/BB8-v2.2/HeadModule6/HeadModule6.ino"

int main(){
  setup();
  fakeNow=50;loop();
  assert(sentPacket.size()==24);
  Packet telemetry;memcpy(&telemetry,sentPacket.data(),24);
  assert(telemetry.flags&FLAG_SOUND);

  uint8_t mac[6]={1,2,3,4,5,6};esp_now_recv_info_t info{mac};
  Packet cmd{};cmd.magic=MAGIC;cmd.version=VERSION;cmd.type=SOUND_COMMAND;cmd.sample_age_ms=1;cmd.sequence=21;cmd.mood=HELLO;
  onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();
  assert(lastToneHz==1200);
  Packet ack;memcpy(&ack,sentPacket.data(),24);
  assert(ack.type==SOUND_ACK);assert(ack.sequence==21);assert(ack.mood==HELLO);

  fakeNow+=80;loop();assert(lastToneHz==0);
  fakeNow+=35;loop();assert(lastToneHz==1700);

  obstacle=true;startMood(ALARM);cmd.sequence=22;cmd.mood=YES;
  uint32_t sendsBeforeBlocked=sentPacketCount;
  onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();
  assert(!soundActive);assert(mood==ALARM);assert(sentPacketCount==sendsBeforeBlocked);

  obstacle=false;cmd.sequence=23;onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();
  assert(soundActive);uint32_t sendsBeforeReplay=sentPacketCount;
  onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();
  assert(sentPacketCount==sendsBeforeReplay);

  cmd.sample_age_ms=2;cmd.sequence=1;onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();
  assert(sentPacketCount==sendsBeforeReplay+1);
  cmd.sample_age_ms=1;cmd.sequence=24;onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));loop();
  assert(sentPacketCount==sendsBeforeReplay+1);

  cmd.mood=SOUND_COUNT;onReceive(&info,(uint8_t*)&cmd,sizeof(cmd));assert(!commandPending);
}
