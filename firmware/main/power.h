#ifndef SH_POWER_H
#define SH_POWER_H
#include <stdbool.h>
#include "esp_err.h"
bool sh_power_wait_for_on(void);
esp_err_t sh_power_start(void (*shutdown)(void));
#endif
