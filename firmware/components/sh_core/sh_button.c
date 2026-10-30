#include "sh_button.h"
#include <string.h>

void sh_button_init(sh_button *b, int running, int pressed, uint32_t now) {
    memset(b, 0, sizeof(*b));
    b->running = !!running;
    b->raw = b->stable = !!pressed;
    b->pressed_at = b->changed_at = now;
    /* Release the power-on gesture before accepting a power-off gesture. */
    b->consumed = running && pressed;
}

enum sh_button_action sh_button_update(sh_button *b, int pressed, uint32_t now) {
    pressed = !!pressed;
    if (pressed != b->raw) {
        b->raw = (uint8_t)pressed;
        b->changed_at = now;
    }
    if (b->raw != b->stable && (uint32_t)(now - b->changed_at) >= 30) {
        b->stable = b->raw;
        if (b->stable) {
            b->pressed_at = b->changed_at;
            b->consumed = 0;
        } else if (b->consumed) {
            b->consumed = 0;
        } else if (!b->running) {
            uint32_t held = b->changed_at - b->pressed_at;
            if (held >= 6000) { b->running = 1; return SH_BUTTON_PAIR; }
            if (held >= 3000) { b->running = 1; return SH_BUTTON_ON; }
            return SH_BUTTON_SLEEP;
        }
    }
    /* Exclude release debounce from the press duration. */
    if (b->stable && b->raw && !b->consumed) {
        uint32_t held = now - b->pressed_at;
        if (!b->running && held >= 6000) {
            b->running = b->consumed = 1;
            return SH_BUTTON_PAIR;
        }
        if (b->running && held >= 3000) {
            b->consumed = 1;
            return SH_BUTTON_SLEEP;
        }
    }
    return SH_BUTTON_NONE;
}
