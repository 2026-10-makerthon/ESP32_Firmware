#ifndef SH_ADAPTERS_H
#define SH_ADAPTERS_H
#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"
esp_err_t sh_capture_read(uint16_t rate,int16_t *pcm,double *normalized,size_t count,uint32_t *first_ms);
esp_err_t sh_output_init(void);
void sh_output_set(uint8_t logical_strength);
void sh_output_off(void);
int sh_output_verified(void);
int sh_output_prototype(void);
int sh_output_healthy(void);
void sh_output_sleep(void);
#endif
