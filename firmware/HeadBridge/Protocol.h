#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
// Fixed byte layout, little endian; no compiler-dependent structs on the radio.
static const size_t PACKET_SIZE = 20;
static const uint8_t RADIO_CHANNEL = 1;
inline void put16(uint8_t *p, uint16_t v) { p[0]=v; p[1]=v>>8; }
inline void put32(uint8_t *p, uint32_t v) { for(int i=0;i<4;i++) p[i]=v>>(8*i); }
inline uint16_t get16(const uint8_t *p) { return uint16_t(p[0]) | uint16_t(p[1])<<8; }
inline uint32_t get32(const uint8_t *p) { uint32_t v=0; for(int i=0;i<4;i++) v |= uint32_t(p[i])<<(8*i); return v; }
inline bool packetValid(const uint8_t *p, size_t n) {
  return n==PACKET_SIZE && p[0]=='R' && p[1]=='C' && p[2]==1 && p[3]<=1;
}
struct TfParser {
  uint8_t frame[9] = {};
  size_t used = 0;
  uint16_t distance = 0, strength = 0;
  bool valid = false;
  bool feed(uint8_t b) {
    if (used==0 && b!=0x59) return false;
    if (used==1 && b!=0x59) { used=0; return false; }
    frame[used++]=b;
    if (used<9) return false;
    uint8_t sum=0; for(int i=0;i<8;i++) sum+=frame[i];
    if(sum!=frame[8]) {
      // Retain a possible header within a corrupted frame for resynchronization.
      size_t start=9;
      for(size_t i=1;i<8;i++) if(frame[i]==0x59 && frame[i+1]==0x59) {start=i; break;}
      if(start<9) {used=9-start; memmove(frame,frame+start,used);}
      else {used=frame[8]==0x59 ? 1 : 0; if(used) frame[0]=0x59;}
      return false;
    }
    used=0; distance=get16(frame+2); strength=get16(frame+4);
    valid=distance>0 && distance<=1200 && strength>=100 && strength!=65535;
    return true;
  }
};
