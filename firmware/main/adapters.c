#include "adapters.h"
#include "sdkconfig.h"
#include "hardware_profile.h"
#include "drv2605.h"
#include "driver/i2s_std.h"
#include "driver/ledc.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>

static i2s_chan_handle_t rx;
static uint16_t current_rate;
static uint8_t last_strength;
static bool output_healthy = true;
static int32_t words[640];
static uint64_t synth_samples;

int sh_output_verified(void) {
#if CONFIG_SH_SIMULATED_HAPTIC
    return 0;
#else
    return SH_HW_VERIFIED && output_healthy;
#endif
}
int sh_output_prototype(void) {
#if CONFIG_SH_SIMULATED_HAPTIC
    return 0;
#else
    return SH_HW_PROTOTYPE && SH_HW_OUTPUT_ENABLED && output_healthy;
#endif
}
esp_err_t sh_output_init(void) {
    last_strength=0;
    output_healthy=false;
#if SH_HAPTIC_BACKEND_DRV2605
    esp_err_t err = sh_drv_init();
    if (err != ESP_OK) {
        output_healthy = false;
        ESP_LOGE("haptic", "DRV2605L unavailable: %s", esp_err_to_name(err));
    }
    else output_healthy=true;
#if SH_HW_OUTPUT_ENABLED && !CONFIG_SH_SIMULATED_HAPTIC
    return err;
#else
    return ESP_OK;
#endif
#elif SH_HW_OUTPUT_ENABLED && !CONFIG_SH_SIMULATED_HAPTIC
    if(!GPIO_IS_VALID_OUTPUT_GPIO(SH_HAPTIC_GPIO)) return ESP_ERR_INVALID_ARG;
    /* Confirm the external driver has an OFF default during reset before enabling. */
    ledc_timer_config_t timer={.speed_mode=LEDC_LOW_SPEED_MODE,.duty_resolution=LEDC_TIMER_10_BIT,
        .timer_num=LEDC_TIMER_0,.freq_hz=SH_HAPTIC_HZ,.clk_cfg=LEDC_AUTO_CLK};
    ESP_RETURN_ON_ERROR(ledc_timer_config(&timer),"haptic","timer");
    ledc_channel_config_t channel={.gpio_num=SH_HAPTIC_GPIO,.speed_mode=LEDC_LOW_SPEED_MODE,
        .channel=LEDC_CHANNEL_0,.intr_type=LEDC_INTR_DISABLE,.timer_sel=LEDC_TIMER_0,.duty=0,.hpoint=0};
    esp_err_t err=ledc_channel_config(&channel);
    output_healthy=err==ESP_OK;
    return err;
#else
    output_healthy=true;
    ESP_LOGI("haptic","physical output disabled; mock driver only");
    return ESP_OK;
#endif
}
void sh_output_set(uint8_t strength) {
    if (!output_healthy || strength > 100) return;
    if(strength==last_strength) return;
    last_strength=strength;
#if SH_HW_OUTPUT_ENABLED && !CONFIG_SH_SIMULATED_HAPTIC
#if SH_HAPTIC_BACKEND_DRV2605
    if (sh_drv_set(strength) != ESP_OK) output_healthy = false;
#else
    uint32_t duty=strength?SH_HAPTIC_WEAK_DUTY+
        ((SH_HAPTIC_STRONG_DUTY-SH_HAPTIC_WEAK_DUTY)*(strength-1)+49)/99:0;
    if(ledc_set_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,duty)!=ESP_OK ||
       ledc_update_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0)!=ESP_OK) {
        ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,0);last_strength=0;
        output_healthy=false;
    }
#endif
#else
    ESP_LOGI("haptic","mock logical strength=%u",strength);
#endif
}
void sh_output_off(void) {sh_output_set(0);}
int sh_output_healthy(void) {
#if CONFIG_SH_SIMULATED_HAPTIC
    return 1;
#else
    return output_healthy;
#endif
}
void sh_output_sleep(void) {
    sh_output_off();
#if SH_HAPTIC_BACKEND_DRV2605
    if (sh_drv_sleep() != ESP_OK) ESP_LOGE("haptic", "standby write failed");
#endif
}

esp_err_t sh_capture_read(uint16_t rate,int16_t *pcm,double *normal,size_t count,uint32_t *first_ms) {
    *first_ms=(uint32_t)(esp_timer_get_time()/1000);
#if CONFIG_SH_SYNTHETIC_AUDIO
    (void)rx;(void)current_rate;(void)words;
    for(size_t i=0;i<count;i++) {
        /* One second quiet, one second tone. Source is explicitly advertised as simulation. */
        double t=(double)(synth_samples+i)/rate;
        double x=(((uint64_t)t)%2)?0.18*sin(2*3.141592653589793*440*t):0;
        normal[i]=x;pcm[i]=(int16_t)(x*32767);
    }
    synth_samples+=count;vTaskDelay(pdMS_TO_TICKS(20));return ESP_OK;
#else
    (void)synth_samples;
    if(!rx) {
        i2s_chan_config_t channel=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO,I2S_ROLE_MASTER);
        channel.dma_desc_num=6;channel.dma_frame_num=160;
        esp_err_t err=i2s_new_channel(&channel,NULL,&rx);if(err!=ESP_OK) return err;
        i2s_std_config_t cfg={.clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(rate),
            .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,I2S_SLOT_MODE_STEREO),
            .gpio_cfg={.mclk=I2S_GPIO_UNUSED,.bclk=CONFIG_SH_I2S_BCLK,.ws=CONFIG_SH_I2S_WS,
                       .dout=I2S_GPIO_UNUSED,.din=CONFIG_SH_I2S_DIN}};
        err=i2s_channel_init_std_mode(rx,&cfg);if(err!=ESP_OK) return err;
        err=i2s_channel_enable(rx);if(err!=ESP_OK) return err;current_rate=rate;
    }
    if(current_rate!=rate) {
        i2s_channel_disable(rx);i2s_std_clk_config_t clk=I2S_STD_CLK_DEFAULT_CONFIG(rate);
        esp_err_t err=i2s_channel_reconfig_std_clock(rx,&clk);if(err!=ESP_OK) return err;
        err=i2s_channel_enable(rx);if(err!=ESP_OK) return err;current_rate=rate;
    }
    size_t bytes=0;
    esp_err_t err=i2s_channel_read(rx,words,count*8,&bytes,100);
    if(err!=ESP_OK || bytes!=count*8) return err==ESP_OK?ESP_ERR_INVALID_SIZE:err;
    /* RX completion minus frame duration estimates the first sample timestamp.
       DMA backlog adds uncertainty; hardware latency requires separate measurement. */
    *first_ms=(uint32_t)(esp_timer_get_time()/1000)-20;
    for(size_t i=0;i<count;i++) {
        /* INMP441: 24 significant bits in a 32-bit Philips slot; verify on the board. */
        int32_t sample24=words[2*i]>>8;
        normal[i]=sample24/8388608.0;
        int32_t sample16=sample24>>8;
        if(sample16>32767) sample16=32767;
        if(sample16< -32768) sample16=-32768;
        pcm[i]=(int16_t)sample16;
    }
    return ESP_OK;
#endif
}
