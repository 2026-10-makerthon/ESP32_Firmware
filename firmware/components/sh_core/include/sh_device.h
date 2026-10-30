#ifndef SH_DEVICE_H
#define SH_DEVICE_H
#include "sh_core.h"

typedef struct {uint8_t data[20],length;} sh_wire_event;
typedef struct {
    uint8_t used,raw[20],raw_length;
    uint16_t id;
    uint32_t received;
    sh_wire_event latest;
} sh_cache;
typedef struct {
    uint8_t body[640],flags;
    uint16_t bytes,seq;
    uint32_t sample;
} sh_frame;
typedef struct {
    uint32_t session,sample,capture_epoch,last_selected,dropped,event_overflows;
    uint16_t stream,seq,mtu,on_unused;
    int16_t on,off;
    uint16_t hold,pre_ms;
    uint8_t verified,simulation,audio_sub,event_sub,armed,transmitting,profile,epoch_valid,selected_valid;
    uint8_t discontinuity,prototype_output;
    sh_command start_command,play_command;
    sh_haptic haptic;
    sh_gate gate;
    sh_cache cache[64];
    sh_wire_event events[32];
    uint8_t event_count;
    sh_frame audio[5],pre[5];
    uint8_t audio_count,pre_count;
} sh_device;

size_t sh_device_size(void);
void sh_device_init(sh_device *d,uint32_t session,int verified,int simulation);
/* Local bench opt-in only; never sets the physical verification capability bit. */
void sh_device_allow_prototype(sh_device *d,int enabled);
void sh_device_disconnect(sh_device *d);
void sh_device_transport(sh_device *d,uint16_t mtu,int audio_sub,int event_sub);
int sh_device_command(sh_device *d,const uint8_t *raw,size_t length,uint32_t now);
void sh_device_tick(sh_device *d,uint32_t now);
int sh_device_capture(sh_device *d,const int16_t *pcm,const double *normalized,size_t count,uint32_t capture_ms);
int sh_device_event_peek(sh_device *d,uint8_t *out);
void sh_device_event_pop(sh_device *d);
int sh_device_audio_packet(sh_device *d,uint16_t offset,uint8_t *out);
void sh_device_audio_pop(sh_device *d);
uint8_t sh_device_state(const sh_device *d);
void sh_device_capabilities(const sh_device *d,uint8_t *out);
#endif
