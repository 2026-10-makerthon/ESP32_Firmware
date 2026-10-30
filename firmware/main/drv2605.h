#ifndef SH_DRV2605_H
#define SH_DRV2605_H
#include "esp_err.h"
#include <stdint.h>
esp_err_t sh_drv_init(void);
esp_err_t sh_drv_set(uint8_t strength);
esp_err_t sh_drv_sleep(void);
#endif
