#include "drv2605.h"
#include "hardware_profile.h"
#include "driver/i2c_master.h"
#include "esp_check.h"

static i2c_master_dev_handle_t driver;
static bool fault;

static esp_err_t write_reg(uint8_t reg, uint8_t value) {
    uint8_t bytes[] = {reg, value};
    return driver ? i2c_master_transmit(driver, bytes, sizeof(bytes), 10) : ESP_ERR_INVALID_STATE;
}

esp_err_t sh_drv_sleep(void) {
    /* Standby first is OFF even if a previous firmware left unsigned RTP format. */
    esp_err_t standby = write_reg(0x01, 0x40);
    esp_err_t zero = write_reg(0x02, 0);
    return standby != ESP_OK ? standby : zero;
}

esp_err_t sh_drv_init(void) {
    i2c_master_bus_handle_t bus;
    i2c_master_bus_config_t cfg = {
        .i2c_port = I2C_NUM_0, .sda_io_num = SH_DRV_SDA, .scl_io_num = SH_DRV_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&cfg, &bus), "drv2605", "bus");
    i2c_device_config_t dev = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = 0x5a, .scl_speed_hz = 400000
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &dev, &driver), "drv2605", "device");
    ESP_RETURN_ON_ERROR(sh_drv_sleep(), "drv2605", "initial standby");
#if SH_HW_OUTPUT_ENABLED
    /* Reviewed or explicit prototype settings; configure with output in standby. */
    const uint8_t regs[] = {SH_DRV_REG_16, SH_DRV_REG_17, SH_DRV_REG_18, SH_DRV_REG_19,
                           SH_DRV_REG_1A, SH_DRV_REG_1B, SH_DRV_REG_1C, SH_DRV_REG_1D};
    for (unsigned i = 0; i < sizeof(regs); ++i)
        ESP_RETURN_ON_ERROR(write_reg(0x16 + i, regs[i]), "drv2605", "configuration");
    ESP_RETURN_ON_ERROR(write_reg(0x0c, 0), "drv2605", "GO off");
    ESP_RETURN_ON_ERROR(write_reg(0x01, 0x05), "drv2605", "real-time playback");
#endif
    return ESP_OK;
}

esp_err_t sh_drv_set(uint8_t strength) {
    if (fault) return ESP_ERR_INVALID_STATE;
    if (strength > 100) return ESP_ERR_INVALID_ARG;
    uint8_t rtp = (uint8_t)((strength * SH_DRV_MAX_RTP + 50) / 100);
    esp_err_t err = write_reg(0x02, rtp);
    if (err != ESP_OK) {
        fault = true; /* Never resume an interrupted pattern after a bus fault. */
        sh_drv_sleep();
    }
    return err;
}
