#include "sh_link.h"
int sh_link_pairing_open(int open, uint32_t started, uint32_t now, uint32_t window_ms) {
    return open && (uint32_t)(now - started) < window_ms;
}
int sh_link_admit(int stopping, int pairing, int known) {
    return !stopping && (pairing || known);
}
int sh_link_authorize(int stopping, int status, int fresh, int pairing,
                      int encrypted, int bonded, int key_size, int known) {
    return !stopping && !status && (!fresh || pairing) && encrypted && bonded &&
           key_size == 16 && known;
}
