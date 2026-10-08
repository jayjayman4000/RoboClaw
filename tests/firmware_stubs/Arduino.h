#pragma once
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <cstdio>
#include <cstdarg>
using std::size_t;
constexpr int LOW=0,HIGH=1,INPUT=0,OUTPUT=1,ADC_11db=3,SERIAL_8N1=0,WIFI_STA=1,WIFI_SECOND_CHAN_NONE=0,ESP_OK=0;
using esp_err_t=int;using portMUX_TYPE=int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
inline uint32_t fakeNow=0;inline int gpioValue[50]{};inline int adcValue=2048;
inline std::vector<uint8_t> sentPacket;
inline uint32_t millis(){return fakeNow;}
inline uint32_t esp_random(){return 1;}
inline void randomSeed(uint32_t){}
inline long random(long a,long){return a;}
inline void pinMode(int,int){}
inline void digitalWrite(int pin,int v){gpioValue[pin]=v;}
inline void analogReadResolution(int){}
inline void analogSetPinAttenuation(int,int){}
inline int analogRead(int){return adcValue;}
inline void ledcWriteTone(int,uint32_t){}
inline void ledcAttach(int,int,int){}
struct FakeSerial {
 std::string output;
 void begin(int){} int available(){return 0;}int read(){return 0;}
 void setRxBufferSize(int){} void begin(int,int,int,int){}
 void print(const char*s){output+=s;}void print(uint32_t n){output+=std::to_string(n);}
 void println(const char*s){output+=s;output+='\n';}
 void printf(const char*fmt,...){char b[2048];va_list a;va_start(a,fmt);vsnprintf(b,sizeof(b),fmt,a);va_end(a);output+=b;}
};
inline FakeSerial Serial;
struct HardwareSerial:FakeSerial {HardwareSerial(int){}};
struct FakeWiFi {void mode(int){}void setSleep(bool){}std::string macAddress(){return "00:00:00:00:00:01";}};
inline FakeWiFi WiFi;
struct esp_now_recv_info_t {const uint8_t*src_addr;};
struct esp_now_peer_info_t {uint8_t peer_addr[6]{};int channel=1;bool encrypt=false;};
inline int esp_wifi_set_channel(int,int){return ESP_OK;}
inline int esp_now_init(){return ESP_OK;}
inline int esp_now_add_peer(const esp_now_peer_info_t*){return ESP_OK;}
inline bool esp_now_is_peer_exist(const uint8_t*){return true;}
inline void esp_now_register_recv_cb(void(*)(const esp_now_recv_info_t*,const uint8_t*,int)){}
inline int esp_now_send(const uint8_t*,const uint8_t*p,size_t n){sentPacket.assign(p,p+n);return ESP_OK;}
