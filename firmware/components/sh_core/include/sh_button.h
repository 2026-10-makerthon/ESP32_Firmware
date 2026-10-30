#ifndef SH_BUTTON_H
#define SH_BUTTON_H
#include <stdint.h>

enum sh_button_action { SH_BUTTON_NONE, SH_BUTTON_SLEEP, SH_BUTTON_ON, SH_BUTTON_PAIR };
typedef struct {
    uint32_t changed_at, pressed_at;
    uint8_t raw, stable, running, consumed;
} sh_button;

/* pressed is logical (1 = button to GND). Time differences wrap as u32. */
void sh_button_init(sh_button *b, int running, int pressed, uint32_t now);
enum sh_button_action sh_button_update(sh_button *b, int pressed, uint32_t now);
#endif
