#include "sh_core.h"
#include <string.h>
#include <math.h>

uint16_t sh_u16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1]<<8)); }
uint32_t sh_u32(const uint8_t *p) { return sh_u16(p) | ((uint32_t)sh_u16(p+2)<<16); }
void sh_put16(uint8_t *p, uint16_t v) { p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8); }
void sh_put32(uint8_t *p, uint32_t v) { sh_put16(p,(uint16_t)v); sh_put16(p+2,(uint16_t)(v>>16)); }

int sh_parse(const uint8_t *r, size_t n, sh_command *o) {
    size_t expected=8;
    if (!r || !o || n<8 || n>20) return SH_BAD_LENGTH;
    if (r[0]!=1) return SH_BAD_VERSION;
    switch(r[1]) {
        case SH_START_AUDIO: expected=9; break;
        case SH_SET_DETECTION: expected=16; break;
        case SH_PLAY: expected=14; break;
        case SH_GET_STATE: case SH_STOP_AUDIO: case SH_STOP: case SH_HEARTBEAT: break;
        default: return SH_UNKNOWN_OPCODE;
    }
    if(n!=expected) return SH_BAD_LENGTH;
    sh_command c={0}; c.opcode=r[1]; c.id=sh_u16(r+2); c.session=sh_u32(r+4);
    if(c.opcode==SH_START_AUDIO) {
        c.profile=r[8]; if(c.profile<1 || c.profile>3) return SH_BAD_VALUE;
    }
    if(c.opcode==SH_SET_DETECTION) {
        c.on=(int16_t)sh_u16(r+8); c.off=(int16_t)sh_u16(r+10);
        c.hold=sh_u16(r+12); c.pre=sh_u16(r+14);
        if(c.on < -9000 || c.on>0 || c.off < -9000 || c.off>c.on-300 ||
           c.hold>5000 || c.pre>100 || c.pre%20) return SH_BAD_VALUE;
    }
    if(c.opcode==SH_PLAY) {
        c.pattern=r[8]; c.strength=r[9]; c.repeat=r[10]; c.ttl=sh_u16(r+12);
        if(c.pattern<1 || c.pattern>5 || c.strength<1 || c.strength>100 ||
           c.repeat<1 || c.repeat>10 || r[11] || c.ttl<1 || c.ttl>5000) return SH_BAD_VALUE;
    }
    *o=c; return SH_OK;
}

static const int steps[89]={7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,
88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,
1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,
7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767};
static const int index_delta[8]={-1,-1,-1,-1,2,4,6,8};
static int clamp(int v,int lo,int hi) {return v<lo?lo:(v>hi?hi:v);}
static void nibble(int code,int *predictor,int *index) {
    int step=steps[*index];
    int diff=(step>>3)+((code&1)?step>>2:0)+((code&2)?step>>1:0)+((code&4)?step:0);
    *predictor=clamp(*predictor+((code&8)?-diff:diff),-32768,32767);
    *index=clamp(*index+index_delta[code&7],0,88);
}
int sh_adpcm_encode(const int16_t *pcm,size_t count,uint8_t initial,uint8_t *out,size_t cap) {
    size_t bytes=4+count/2;
    if(!pcm || !out || !count || initial>88 || cap<bytes) return -1;
    int predictor=pcm[0], index=initial;
    memset(out,0,bytes); sh_put16(out,(uint16_t)predictor); out[2]=initial;
    for(size_t i=1;i<count;i++) {
        int d=(int)pcm[i]-predictor, code=d<0?8:0, step=steps[index];
        if(d<0) d=-d;
        if(d>=step) {code|=4; d-=step;}
        if(d>=step>>1) {code|=2; d-=step>>1;}
        if(d>=step>>2) code|=1;
        nibble(code,&predictor,&index);
        out[4+(i-1)/2] |= (uint8_t)(code << (4*((i-1)%2)));
    }
    return (int)bytes;
}
int sh_adpcm_decode(const uint8_t *b,size_t n,size_t count,int16_t *out) {
    if(!b || !out || !count || n!=4+count/2) return SH_BAD_LENGTH;
    if(b[2]>88 || b[3] || (!(count%2) && (b[n-1]&0xf0))) return SH_BAD_VALUE;
    int predictor=(int16_t)sh_u16(b),index=b[2]; out[0]=(int16_t)predictor;
    for(size_t i=1;i<count;i++) {
        int code=(b[4+(i-1)/2]>>(4*((i-1)%2)))&15;
        nibble(code,&predictor,&index); out[i]=(int16_t)predictor;
    }
    return SH_OK;
}

static const uint16_t sos_ms[17]={120,120,120,120,120,360,360,120,360,120,360,360,120,120,120,120,120};
static uint32_t single_duration(uint8_t p) {
    if(p==1) return 200;
    if(p==2) return 450;
    if(p==3) return 700;
    if(p==4) return 1000;
    if(p==5) {uint32_t n=0;for(int i=0;i<17;i++) n+=sos_ms[i];return n;} return 0;
}
uint32_t sh_pattern_duration(uint8_t p,uint8_t repeat) {
    if(p<1 || p>5 || repeat<1 || repeat>10) return 0;
    return single_duration(p)*repeat+200u*(repeat-1);
}
uint8_t sh_pattern_level(uint8_t p,uint8_t strength,uint8_t repeat,uint32_t age) {
    uint32_t unit=single_duration(p);
    if(!unit || !repeat || age>=sh_pattern_duration(p,repeat)) return 0;
    age %= unit+200;
    if(age>=unit) return 0;
    if(p==2) return age>=150 && age<300 ? 0:strength;
    if(p==4) {uint32_t level=(age/5)*100/199;return (uint8_t)((strength*level+50)/100);}
    if(p==5) {for(int i=0;i<17;i++) {if(age<sos_ms[i]) return (i%2)?0:strength;age-=sos_ms[i];}}
    return strength;
}
void sh_haptic_init(sh_haptic *s) {memset(s,0,sizeof(*s));}
void sh_haptic_stop(sh_haptic *s) {s->active=0;s->level=0;}
void sh_haptic_tick(sh_haptic *s,uint32_t now) {
    if(!s->active) return;
    uint32_t age=now-s->started;
    if(now-s->heartbeat>=1500) {sh_haptic_stop(s);s->reason=SH_LEASE_EXPIRED;}
    else if(age>=sh_pattern_duration(s->pattern,s->repeat)) {sh_haptic_stop(s);s->reason=SH_OK;}
    else if(age>=s->ttl) {sh_haptic_stop(s);s->reason=SH_TTL_EXPIRED;}
    else s->level=sh_pattern_level(s->pattern,s->strength,s->repeat,age);
}
void sh_haptic_heartbeat(sh_haptic *s,uint32_t now) {sh_haptic_tick(s,now);s->heartbeat=now;}
int sh_haptic_start(sh_haptic *s,uint8_t p,uint8_t strength,uint8_t repeat,uint16_t ttl,uint32_t now,int verified) {
    sh_haptic_tick(s,now);
    if(!verified) return SH_HARDWARE_UNVERIFIED;
    if(p<1 || p>5 || strength<1 || strength>100 || repeat<1 || repeat>10 || !ttl || ttl>5000 || sh_pattern_duration(p,repeat)>ttl) return SH_BAD_VALUE;
    if(s->active) return SH_BUSY;
    if(now-s->heartbeat>=1500) return SH_LEASE_EXPIRED;
    s->pattern=p;s->strength=strength;s->repeat=repeat;s->ttl=ttl;s->started=now;s->active=1;s->reason=0;
    s->level=sh_pattern_level(p,strength,repeat,0);return SH_OK;
}

void sh_gate_init(sh_gate *s,uint16_t rate,int16_t on,int16_t off,uint16_t hold) {
    memset(s,0,sizeof(*s));s->rate=rate;s->size=rate/100;s->hop=rate/200;s->on=on;s->off=off;s->hold=hold;s->level=-120;
}
uint8_t sh_gate_feed(sh_gate *s,double x) {
    if(!s->size || s->size>160 || !s->hop) return 0;
    double previous=s->window[s->cursor];
    s->sum+=x-previous;s->sum2+=x*x-previous*previous;s->window[s->cursor]=x;
    s->cursor=(s->cursor+1)%s->size;if(s->fill<s->size) s->fill++;
    s->samples++;
    if(s->fill<s->size || s->samples%s->hop) return 0;
    double mean=s->sum/s->size,power=s->sum2/s->size-mean*mean;
    s->level=10*log10(fmax(power,1e-12));
    if(!s->active && s->level*100+1e-8>=s->on) {s->active=1;s->quiet=0;return 1;}
    if(s->active) {
        if(s->level*100+1e-8>=s->off) s->quiet=0;
        else {s->quiet+=5;if(s->quiet>=s->hold) {s->active=0;s->quiet=0;return 2;}}
    }
    return 0;
}
size_t sh_event(uint8_t *out,uint8_t op,uint16_t id,uint32_t session,uint8_t status,uint8_t detail,uint32_t now,const uint8_t *extra,size_t n) {
    if(n>6 || (n && !extra)) return 0;
    out[0]=1;out[1]=op;sh_put16(out+2,id);sh_put32(out+4,session);out[8]=status;out[9]=detail;sh_put32(out+10,now);
    if(n) memcpy(out+14,extra,n);
    return 14+n;
}
void sh_audio_header(uint8_t *o,uint8_t flags,uint8_t profile,uint16_t stream,uint16_t seq,uint32_t sample,uint16_t bytes,uint16_t offset) {
    o[0]=1;o[1]=1;o[2]=flags;o[3]=profile;sh_put16(o+4,stream);sh_put16(o+6,seq);sh_put32(o+8,sample);sh_put16(o+12,bytes);sh_put16(o+14,offset);
}
