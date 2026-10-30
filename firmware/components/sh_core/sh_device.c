#include "sh_device.h"
#include <string.h>

size_t sh_device_size(void) {return sizeof(sh_device);}
void sh_device_init(sh_device *d,uint32_t session,int verified,int simulation) {
    memset(d,0,sizeof(*d));d->session=session?session:1;d->verified=!!verified;d->simulation=!!simulation;
    d->mtu=23;d->on=-4500;d->off=-5000;d->hold=500;d->pre_ms=100;
    sh_gate_init(&d->gate,16000,d->on,d->off,d->hold);
}
void sh_device_disconnect(sh_device *d) {
    uint32_t session=d->session;int verified=d->verified,simulation=d->simulation,prototype=d->prototype_output;
    sh_device_init(d,session,verified,simulation);
    d->prototype_output=(uint8_t)prototype;
}
void sh_device_allow_prototype(sh_device *d,int enabled) {
    d->prototype_output=!!enabled;
    if(!enabled && !d->verified && !d->simulation) sh_haptic_stop(&d->haptic);
}
void sh_device_transport(sh_device *d,uint16_t mtu,int audio_sub,int event_sub) {
    d->mtu=mtu;d->audio_sub=!!audio_sub;d->event_sub=!!event_sub;
    if(!d->event_sub) sh_haptic_stop(&d->haptic);
    if(!d->event_sub || !d->audio_sub) {
        d->armed=d->transmitting=d->audio_count=d->pre_count=d->epoch_valid=0;
    }
}
uint8_t sh_device_state(const sh_device *d) {
    return (d->armed?1:0)|(d->transmitting?2:0)|(d->haptic.active?4:0)|(d->verified?8:0)|
           (d->audio_sub?16:0)|(d->event_sub?32:0);
}
void sh_device_capabilities(const sh_device *d,uint8_t *out) {
    memset(out,0,20);out[0]=1;out[2]=(uint8_t)(14|(d->verified?1:0)|(d->simulation?16:0));
    out[3]=7;out[4]=31;out[5]=100;sh_put16(out+6,10);sh_put16(out+8,5000);
    sh_put16(out+10,500);sh_put16(out+12,1500);sh_put16(out+14,185);sh_put16(out+16,244);
}
static int cache_find(sh_device *d,uint16_t id) {
    for(int i=0;i<64;i++) if(d->cache[i].used && d->cache[i].id==id) return i;
    return -1;
}
static void enqueue(sh_device *d,const sh_wire_event *event) {
    if(d->event_count==32) {
        sh_haptic_stop(&d->haptic);d->event_overflows++;
        memmove(d->events,d->events+1,31*sizeof(d->events[0]));d->event_count--;
    }
    d->events[d->event_count++]=*event;
}
static void emit(sh_device *d,const sh_command *c,uint8_t status,uint8_t detail,uint32_t now,
                 const uint8_t *extra,size_t n,int update_cache) {
    sh_wire_event e={0};
    e.length=(uint8_t)sh_event(e.data,c->opcode,c->id,d->session,status,detail,now,extra,n);
    if(update_cache) {int i=cache_find(d,c->id);if(i>=0) d->cache[i].latest=e;}
    enqueue(d,&e);
}
static void end_haptic(sh_device *d,uint32_t now,uint8_t reason,int completed) {
    if(!d->haptic.active) return;
    sh_haptic_stop(&d->haptic);
    emit(d,&d->play_command,completed?SH_COMPLETED:SH_STOPPED,reason,now,NULL,0,1);
}
void sh_device_tick(sh_device *d,uint32_t now) {
    uint8_t was=d->haptic.active;
    sh_haptic_tick(&d->haptic,now);
    if(was && !d->haptic.active) emit(d,&d->play_command,d->haptic.reason?SH_STOPPED:SH_COMPLETED,
                                     d->haptic.reason,now,NULL,0,1);
}
int sh_device_command(sh_device *d,const uint8_t *r,size_t n,uint32_t now) {
    sh_command c={0};int error=sh_parse(r,n,&c);
    if(error) {
        if(n>=8) {c.opcode=r[1];c.id=sh_u16(r+2);emit(d,&c,SH_REJECTED,(uint8_t)error,now,NULL,0,0);}
        return error;
    }
    if(c.session!=d->session && !(c.opcode==SH_GET_STATE && c.session==0)) {
        emit(d,&c,SH_REJECTED,SH_SESSION_MISMATCH,now,NULL,0,0);return SH_SESSION_MISMATCH;
    }
    if(c.opcode==SH_HEARTBEAT) {
        if(cache_find(d,c.id)>=0) {emit(d,&c,SH_REJECTED,SH_COMMAND_ID_CONFLICT,now,NULL,0,0);return SH_COMMAND_ID_CONFLICT;}
        sh_device_tick(d,now);d->haptic.heartbeat=now;
        emit(d,&c,SH_COMPLETED,0,now,NULL,0,0);return SH_OK;
    }
    for(int i=0;i<64;i++) if(d->cache[i].used && now-d->cache[i].received>=60000 &&
       !(d->armed && d->start_command.id==d->cache[i].id) &&
       !(d->haptic.active && d->play_command.id==d->cache[i].id)) d->cache[i].used=0;
    int slot=cache_find(d,c.id);
    if(slot>=0) {
        if(d->cache[slot].raw_length!=n || memcmp(d->cache[slot].raw,r,n)) {
            emit(d,&c,SH_REJECTED,SH_COMMAND_ID_CONFLICT,now,NULL,0,0);return SH_COMMAND_ID_CONFLICT;
        }
        enqueue(d,&d->cache[slot].latest);return SH_OK;
    }
    for(int i=0;i<64;i++) if(!d->cache[i].used) {slot=i;break;}
    if(slot<0 && c.opcode!=SH_STOP && c.opcode!=SH_STOP_AUDIO && c.opcode!=SH_HEARTBEAT) {
        emit(d,&c,SH_REJECTED,SH_CACHE_FULL,now,NULL,0,0);return SH_CACHE_FULL;
    }
    if(slot>=0) {
        sh_cache *entry=&d->cache[slot];memset(entry,0,sizeof(*entry));entry->used=1;
        entry->id=c.id;entry->received=now;entry->raw_length=(uint8_t)n;memcpy(entry->raw,r,n);
    }
    uint8_t status=SH_COMPLETED,extra[6]={0};size_t extra_n=0;
    if(c.opcode==SH_GET_STATE) {
        sh_put16(extra,d->stream);extra[2]=sh_device_state(d);extra[3]=d->armed?d->profile:0;extra_n=4;
    } else if(c.opcode==SH_STOP) {end_haptic(d,now,0,0);status=SH_STOPPED;
    } else if(c.opcode==SH_STOP_AUDIO) {
        if(d->armed) emit(d,&d->start_command,SH_STOPPED,0,now,NULL,0,1);
        d->armed=d->transmitting=d->audio_count=d->pre_count=d->epoch_valid=0;status=SH_STOPPED;
        sh_gate_init(&d->gate,16000,d->on,d->off,d->hold);
    } else if(!d->event_sub) error=SH_NOT_SUBSCRIBED;
    else if(c.opcode==SH_SET_DETECTION) {
        if(d->armed) error=SH_BUSY;
        else {d->on=c.on;d->off=c.off;d->hold=c.hold;d->pre_ms=c.pre;}
    } else if(c.opcode==SH_START_AUDIO) {
        if(d->armed) error=SH_BUSY;
        else if(!d->audio_sub) error=SH_NOT_SUBSCRIBED;
        else if(d->mtu<185) error=SH_MTU_TOO_SMALL;
        else {
            d->stream++;d->profile=c.profile;d->seq=0;d->sample=0;d->epoch_valid=0;d->selected_valid=0;
            d->audio_count=d->pre_count=d->transmitting=d->discontinuity=0;d->armed=1;d->start_command=c;
            sh_gate_init(&d->gate,c.profile==2?8000:16000,d->on,d->off,d->hold);status=SH_ACCEPTED;
        }
    } else if(c.opcode==SH_PLAY) {
        sh_device_tick(d,now);
        error=sh_haptic_start(&d->haptic,c.pattern,c.strength,c.repeat,c.ttl,now,
                              d->verified||d->simulation||d->prototype_output);
        if(!error) {d->play_command=c;status=SH_STARTED;}
    }
    emit(d,&c,error?SH_REJECTED:status,(uint8_t)error,now,extra,extra_n,1);
    return error;
}

static void select_frame(sh_device *d,const sh_frame *source,uint8_t extra_flags) {
    sh_frame frame=*source;frame.flags|=extra_flags;frame.seq=d->seq++;
    d->last_selected=frame.sample;d->selected_valid=1;
    if(d->audio_count==5) {
        int victim=0;
        for(int i=0;i<5;i++) if(d->audio[i].flags&SH_PRE_ROLL) {victim=i;break;}
        uint8_t start=d->audio[victim].flags&SH_BURST_START;
        memmove(d->audio+victim,d->audio+victim+1,(size_t)(4-victim)*sizeof(sh_frame));d->audio_count--;
        if(start) {if(victim<d->audio_count) d->audio[victim].flags|=SH_BURST_START;else frame.flags|=SH_BURST_START;}
        d->dropped++;d->discontinuity=1;
    }
    d->audio[d->audio_count++]=frame;
}
int sh_device_capture(sh_device *d,const int16_t *pcm,const double *normal,size_t count,uint32_t now) {
    if(count!=160 && count!=320) return SH_BAD_LENGTH;
    /* The microphone remains sampled by the capture adapter even while disarmed. */
    if(!d->armed) {
        for(size_t i=0;i<count;i++) sh_gate_feed(&d->gate,normal?normal[i]:pcm[i]/32768.0);
        return SH_OK;
    }
    if(count!=(d->profile==2?160u:320u)) return SH_BAD_LENGTH;
    if(!d->epoch_valid) {
        d->capture_epoch=now;d->epoch_valid=1;uint8_t extra[6];sh_put16(extra,d->stream);sh_put32(extra+2,now);
        emit(d,&d->start_command,SH_STARTED,0,now,extra,6,1);
    }
    uint8_t started=0;
    for(size_t i=0;i<count;i++) started|=sh_gate_feed(&d->gate,normal?normal[i]:pcm[i]/32768.0)&1;
    sh_frame current={0};current.sample=d->sample;current.flags=d->haptic.level?SH_MOTOR:0;
    if(d->profile==3) {current.bytes=640;for(size_t i=0;i<count;i++) sh_put16(current.body+2*i,(uint16_t)pcm[i]);}
    else current.bytes=(uint16_t)sh_adpcm_encode(pcm,count,0,current.body,sizeof(current.body));
    if(!d->transmitting && started) {
        int first=1;
        for(int i=0;i<d->pre_count;i++) {
            if(!d->selected_valid || (int32_t)(d->pre[i].sample-d->last_selected)>0) {
                select_frame(d,&d->pre[i],SH_PRE_ROLL|(first?SH_BURST_START:0));first=0;
            }
        }
        select_frame(d,&current,(first?SH_BURST_START:0)|(!d->gate.active?SH_BURST_END:0));
        d->transmitting=d->gate.active;
    } else if(d->transmitting) {
        select_frame(d,&current,d->gate.active?0:SH_BURST_END);d->transmitting=d->gate.active;
    }
    int capacity=d->pre_ms/20;
    if(capacity) {
        if(d->pre_count>=capacity) {memmove(d->pre,d->pre+1,(size_t)(capacity-1)*sizeof(sh_frame));d->pre_count--;}
        d->pre[d->pre_count++]=current;
    }
    d->sample+=(uint32_t)count;return SH_OK;
}
int sh_device_event_peek(sh_device *d,uint8_t *out) {
    if(!d->event_count) return 0;
    memcpy(out,d->events[0].data,d->events[0].length);
    return d->events[0].length;
}
void sh_device_event_pop(sh_device *d) {
    if(d->event_count) {d->event_count--;memmove(d->events,d->events+1,d->event_count*sizeof(d->events[0]));}
}
int sh_device_audio_packet(sh_device *d,uint16_t offset,uint8_t *out) {
    if(!d->audio_count || !d->armed || !d->audio_sub || d->mtu<185) return 0;
    sh_frame *f=&d->audio[0];if(offset>=f->bytes) return 0;
    unsigned capacity=d->mtu-3;if(capacity>244) capacity=244;capacity-=16;
    unsigned remaining=f->bytes-offset;if(capacity>remaining) capacity=remaining;
    if(!offset && d->discontinuity) {f->flags|=SH_DISCONTINUITY;d->discontinuity=0;}
    sh_audio_header(out,f->flags,d->profile,d->stream,f->seq,f->sample,f->bytes,offset);
    memcpy(out+16,f->body+offset,capacity);return (int)capacity+16;
}
void sh_device_audio_pop(sh_device *d) {
    if(d->audio_count) {d->audio_count--;memmove(d->audio,d->audio+1,d->audio_count*sizeof(sh_frame));}
}
