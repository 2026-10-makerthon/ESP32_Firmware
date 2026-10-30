#include "power.h"
#include "sdkconfig.h"
#include "sh_button.h"
#include "adapters.h"
#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#if CONFIG_SH_POWER_BUTTON
static uint32_t millis(void) { return (uint32_t)(esp_timer_get_time() / 1000); }
static int pressed(void) { return gpio_get_level(CONFIG_SH_BUTTON_GPIO) == 0; }

static void sleep_off(void) {
    sh_output_sleep();
    /* EXT0 is level-sensitive: arming while still held would wake immediately. */
    uint32_t released_at = millis();
    while ((uint32_t)(millis() - released_at) < 50) {
        if (pressed()) released_at = millis();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    ESP_ERROR_CHECK(rtc_gpio_init(CONFIG_SH_BUTTON_GPIO));
    ESP_ERROR_CHECK(rtc_gpio_set_direction(CONFIG_SH_BUTTON_GPIO, RTC_GPIO_MODE_INPUT_ONLY));
    ESP_ERROR_CHECK(rtc_gpio_pullup_en(CONFIG_SH_BUTTON_GPIO));
    ESP_ERROR_CHECK(rtc_gpio_pulldown_dis(CONFIG_SH_BUTTON_GPIO));
    ESP_ERROR_CHECK(esp_sleep_enable_ext0_wakeup(CONFIG_SH_BUTTON_GPIO, 0));
    ESP_LOGI("power", "OFF (deep sleep); hold button 3s then release, or 6s for pairing");
    esp_deep_sleep_start();
}

static void (*shutdown_hook)(void);
static void power_task(void *unused) {
    (void)unused;
    sh_button button;
    sh_button_init(&button, true, pressed(), millis());
    for (;;) {
        if (sh_button_update(&button, pressed(), millis()) == SH_BUTTON_SLEEP) {
            shutdown_hook();
            sleep_off();
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
#endif

bool sh_power_wait_for_on(void) {
#if CONFIG_SH_POWER_BUTTON
    ESP_ERROR_CHECK(rtc_gpio_deinit(CONFIG_SH_BUTTON_GPIO));
    gpio_config_t input = {.pin_bit_mask = 1ULL << CONFIG_SH_BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT, .pull_up_en = GPIO_PULLUP_ENABLE};
    ESP_ERROR_CHECK(gpio_config(&input));
    if (!pressed()) sleep_off();
    sh_button button;
    sh_button_init(&button, false, true, millis());
    for (;;) {
        enum sh_button_action action = sh_button_update(&button, pressed(), millis());
        if (action == SH_BUTTON_SLEEP) sleep_off();
        if (action == SH_BUTTON_ON || action == SH_BUTTON_PAIR) {
            ESP_LOGI("power", "%s", action == SH_BUTTON_PAIR ? "ON / pairing" : "ON / reconnect");
            return action == SH_BUTTON_PAIR;
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
#else
    /* Explicit development configuration without a button. */
    return true;
#endif
}

esp_err_t sh_power_start(void (*shutdown)(void)) {
#if CONFIG_SH_POWER_BUTTON
    shutdown_hook = shutdown;
    return xTaskCreate(power_task, "power", 4096, NULL, 7, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
#else
    (void)shutdown;
    return ESP_OK;
#endif
}
