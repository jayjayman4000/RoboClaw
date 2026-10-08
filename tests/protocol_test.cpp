#include "../firmware/HeadBridge/Protocol.h"
#include <cassert>
int main() {
  uint8_t p[PACKET_SIZE]={}; p[0]='R';p[1]='C';p[2]=1;p[3]=1;
  put16(p+4,1200);put32(p+8,0xfefdfcfb);
  assert(get16(p+4)==1200 && get32(p+8)==0xfefdfcfb);
  assert(packetValid(p,20) && !packetValid(p,19));
  p[2]=2;assert(!packetValid(p,20));
  TfParser parser;
  uint8_t f[9]={0x59,0x59,125,0,0x2c,1,0,0,0};
  for(int i=0;i<8;i++) f[8]+=f[i];
  assert(!parser.feed(0));
  for(int i=0;i<8;i++) assert(!parser.feed(f[i]));
  assert(parser.feed(f[8]));assert(parser.valid && parser.distance==125 && parser.strength==300);
  f[4]=0xff;f[5]=0xff;f[8]=0;for(int i=0;i<8;i++) f[8]+=f[i];
  for(int i=0;i<9;i++) parser.feed(f[i]);assert(!parser.valid);
  f[8]++;for(int i=0;i<9;i++) assert(!parser.feed(f[i]));
}
