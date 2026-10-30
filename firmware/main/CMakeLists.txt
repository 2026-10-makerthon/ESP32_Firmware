idf_component_register(SRCS "main.c" "adapters.c" "drv2605.c" "power.c" INCLUDE_DIRS "."
    REQUIRES sh_core bt nvs_flash esp_timer esp_driver_i2s esp_driver_i2c esp_driver_ledc esp_driver_gpio esp_hw_support)
