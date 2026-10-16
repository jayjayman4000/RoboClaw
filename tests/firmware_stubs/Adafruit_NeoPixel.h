#pragma once
#include <cstdint>
#include <vector>

constexpr uint16_t NEO_GRB=0x01;
constexpr uint16_t NEO_KHZ800=0x02;

class Adafruit_NeoPixel {
 public:
  Adafruit_NeoPixel(uint16_t count, int16_t pin, uint16_t type)
      : count_(count), pin_(pin), type_(type), pixels_(count, 0) {}
  void begin(){begun_=true;}
  void setBrightness(uint8_t value){brightness_=value;}
  uint32_t Color(uint8_t red,uint8_t green,uint8_t blue) const {
    return (uint32_t(red)<<16)|(uint32_t(green)<<8)|blue;
  }
  void fill(uint32_t color,uint16_t first=0,uint16_t count=0){
    if(count==0 || first+count>count_)count=count_-first;
    for(uint16_t i=first;i<first+count;i++)pixels_[i]=color;
  }
  void clear(){fill(0);}
  void show(){showCount_++;}
  uint16_t numPixels() const{return count_;}
  int16_t getPin() const{return pin_;}
  uint8_t getBrightness() const{return brightness_;}
  uint32_t getPixelColor(uint16_t index) const{return pixels_.at(index);}
  bool begun() const{return begun_;}
  uint32_t showCount() const{return showCount_;}
 private:
  uint16_t count_;
  int16_t pin_;
  uint16_t type_;
  std::vector<uint32_t> pixels_;
  uint8_t brightness_=255;
  bool begun_=false;
  uint32_t showCount_=0;
};
