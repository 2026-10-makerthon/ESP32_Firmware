#ifndef SH_CORE_H
#define SH_CORE_H
#include <stdint.h>
#include <stddef.h>

enum { SH_OK=0, SH_BAD_LENGTH=1, SH_BAD_VERSION=2, SH_BAD_VALUE=3, SH_BUSY=4,
       SH_SESSION_MISMATCH=5, SH_HARDWARE_UNVERIFIED=6, SH_MTU_TOO_SMALL=7,
       SH_INTERNAL=8, SH_UNKNOWN_OPCODE=9, SH_COMMAND_ID_CONFLICT=10,
       SH_NOT_SUBSCRIBED=11, SH_LEASE_EXPIRED=12, SH_TTL_EXPIRED=13, SH_CACHE_FULL=14 };
enum { SH_GET_STATE=1, SH_START_AUDIO=2, SH_STOP_AUDIO=3, SH_SET_DETECTION=4,
       SH_PLAY=16, SH_STOP=17, SH_HEARTBEAT=32 };
enum { SH_ACCEPTED=1, SH_STARTED=2, SH_COMPLETED=3, SH_STOPPED=4, SH_REJECTED=5 };
enum { SH_MOTOR=1, SH_DISCONTINUITY=2, SH_BURST_START=4, SH_BURST_END=8, SH_PRE_ROLL=16 };

typedef struct {
    uint8_t opcode;
    uint16_t id;
    uint32_t session;
    uint8_t profile, pattern, strength, repeat;
    uint16_t ttl, hold, pre;
    int16_t on, off;
} sh_command;

uint16_t sh_u16(const uint8_t *p);
uint32_t sh_u32(const uint8_t *p);
void sh_put16(uint8_t *p, uint16_t v);
void sh_put32(uint8_t *p, uint32_t v);
int sh_parse(const uint8_t *raw, size_t length, sh_command *out);
int sh_adpcm_encode(const int16_t *pcm, size_t count, uint8_t initial_index, uint8_t *out, size_t capacity);
int sh_adpcm_decode(const uint8_t *block, size_t length, size_t count, int16_t *out);
uint32_t sh_pattern_duration(uint8_t pattern, uint8_t repeat);
uint8_t sh_pattern_level(uint8_t pattern, uint8_t strength, uint8_t repeat, uint32_t elapsed);

typedef struct {
    uint32_t started, heartbeat;
    uint16_t ttl;
    uint8_t pattern, strength, repeat, active, level, reason;
} sh_haptic;
void sh_haptic_init(sh_haptic *s);
int sh_haptic_start(sh_haptic *s, uint8_t pattern, uint8_t strength, uint8_t repeat,
                    uint16_t ttl, uint32_t now, int verified);
void sh_haptic_tick(sh_haptic *s, uint32_t now);
void sh_haptic_stop(sh_haptic *s);
void sh_haptic_heartbeat(sh_haptic *s, uint32_t now);

typedef struct {
    double window[160], sum, sum2, level;
    uint32_t samples;
    uint16_t rate, size, hop, fill, cursor, quiet, hold;
    int16_t on, off;
    uint8_t active;
} sh_gate;
void sh_gate_init(sh_gate *s, uint16_t rate, int16_t on, int16_t off, uint16_t hold);
/* one normalized pre-gain sample; bit0=start, bit1=end */
uint8_t sh_gate_feed(sh_gate *s, double sample);

size_t sh_event(uint8_t *out, uint8_t opcode, uint16_t id, uint32_t session,
                uint8_t status, uint8_t detail, uint32_t now, const uint8_t *extra, size_t length);
void sh_audio_header(uint8_t *out, uint8_t flags, uint8_t profile, uint16_t stream,
                     uint16_t seq, uint32_t sample, uint16_t bytes, uint16_t offset);
#endif
