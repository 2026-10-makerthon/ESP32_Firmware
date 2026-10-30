"""Run the actual driver against an I2C recorder; no hardware is energized."""
import ctypes as C
import os
from pathlib import Path
import subprocess
import sys
import importlib.util
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", params=["reviewed_fixture", "dm161_prototype"])
def driver(tmp_path_factory,request):
    work=tmp_path_factory.mktemp("drv2605")
    (work/"driver").mkdir()
    for name in ("drv2605.c","drv2605.h"):
        (work/name).write_text((ROOT/"firmware/main"/name).read_text(),encoding="utf-8")
    if request.param=="dm161_prototype":
        spec=importlib.util.spec_from_file_location("hardware_header_drv",ROOT/"scripts/hardware-header.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        profile=json.loads((ROOT/"hardware/profiles/xiao-dm161-3v-prototype.json").read_text())
        header=module.generate(profile)
        assert "#define SH_HW_VERIFIED 0\n" in header
        expected_regs=[141,138,0x0c,0x6c,0x36,0x13,0xf5,0xa0]
        max_rtp=127
    else:
        # Deliberately fictional register values for software tests only.
        header=("#define SH_HW_VERIFIED 1\n#define SH_HW_OUTPUT_ENABLED 1\n#define SH_DRV_SDA 5\n#define SH_DRV_SCL 6\n#define SH_DRV_MAX_RTP 64\n"+
            "".join(f"#define SH_DRV_REG_{reg:02X} {reg}\n" for reg in range(0x16,0x1e)))
        expected_regs=list(range(0x16,0x1e));max_rtp=64
    (work/"hardware_profile.h").write_text(header)
    (work/"esp_err.h").write_text("#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_ERR_INVALID_STATE 1\n#define ESP_ERR_INVALID_ARG 2\n")
    (work/"esp_check.h").write_text("#define ESP_RETURN_ON_ERROR(expr,tag,msg) do {int rc=(expr);if(rc)return rc;}while(0)\n")
    (work/"driver/i2c_master.h").write_text("""
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef void *i2c_master_dev_handle_t;
typedef void *i2c_master_bus_handle_t;
typedef struct {int i2c_port,sda_io_num,scl_io_num,clk_source,glitch_ignore_cnt;
    struct {bool enable_internal_pullup;} flags;} i2c_master_bus_config_t;
typedef struct {int dev_addr_length,device_address,scl_speed_hz;} i2c_device_config_t;
#define I2C_NUM_0 0
#define I2C_CLK_SRC_DEFAULT 0
#define I2C_ADDR_BIT_LEN_7 0
int i2c_new_master_bus(const i2c_master_bus_config_t *,i2c_master_bus_handle_t *);
int i2c_master_bus_add_device(i2c_master_bus_handle_t,const i2c_device_config_t *,i2c_master_dev_handle_t *);
int i2c_master_transmit(i2c_master_dev_handle_t,const uint8_t *,size_t,int);
""")
    (work/"record.c").write_text("""
#include "drv2605.c"
static int count, fail_at;
static uint8_t history[128][2];
int i2c_new_master_bus(const i2c_master_bus_config_t *cfg,i2c_master_bus_handle_t *bus) {
    if(cfg->sda_io_num!=5 || cfg->scl_io_num!=6)return 9;
    *bus=(void*)1;return 0;
}
int i2c_master_bus_add_device(i2c_master_bus_handle_t bus,const i2c_device_config_t *cfg,i2c_master_dev_handle_t *dev) {
    if(!bus || cfg->device_address!=0x5a)return 9;
    *dev=(void*)1;return 0;
}
int i2c_master_transmit(i2c_master_dev_handle_t dev,const uint8_t *data,size_t len,int timeout) {
    if(!dev || len!=2 || timeout!=10 || count>=128)return 9;
    history[count][0]=data[0];history[count][1]=data[1];count++;
    return count==fail_at ? 9 : 0;
}
void recorder_reset(int failure) {count=0;fail_at=failure;fault=false;driver=NULL;}
int recorder_count(void) {return count;}
int recorder_value(int i,int col) {return history[i][col];}
""")
    out=work/"driver.dll"
    env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(ROOT/".tools/zig-cache"),
             ZIG_LOCAL_CACHE_DIR=str(ROOT/".tools/zig-cache/local"),
             TMP=str(ROOT/".tools/tmp"),TEMP=str(ROOT/".tools/tmp"))
    result=subprocess.run([sys.executable,"-m","ziglang","cc","-shared","-std=c11","-Wall","-Werror",
                           "-I",str(work),str(work/"record.c"),"-o",str(out)],
                          env=env,capture_output=True,encoding="utf-8",errors="replace")
    assert result.returncode==0,result.stderr
    dll=C.CDLL(str(out))
    dll.sh_drv_set.argtypes=[C.c_uint8]
    dll.expected_regs=expected_regs
    dll.max_rtp=max_rtp
    return dll


def history(driver):
    return [(driver.recorder_value(i,0),driver.recorder_value(i,1)) for i in range(driver.recorder_count())]


def test_configuration_is_applied_before_rtp_and_stop_is_zero(driver):
    driver.recorder_reset(0)
    assert driver.sh_drv_init()==0
    assert history(driver)==[(1,0x40),(2,0)]+list(zip(range(0x16,0x1e),driver.expected_regs))+[(0x0c,0),(1,5)]
    assert driver.sh_drv_set(50)==0
    assert driver.sh_drv_set(100)==0
    assert driver.sh_drv_set(0)==0
    assert history(driver)[-3:]==[(2,(50*driver.max_rtp+50)//100),(2,driver.max_rtp),(2,0)]
    assert driver.sh_drv_sleep()==0
    assert history(driver)[-2:]==[(1,0x40),(2,0)]


def test_bus_error_attempts_both_stop_writes_and_latches_fault(driver):
    driver.recorder_reset(13)  # first actual output after 12 successful init writes
    assert driver.sh_drv_init()==0
    assert driver.sh_drv_set(80)!=0
    assert history(driver)[-2:]==[(1,0x40),(2,0)]
    before=history(driver)
    assert driver.sh_drv_set(10)!=0
    assert history(driver)==before  # no automatic resumption after the bus recovers


def test_failed_standby_still_zeroes_rtp_and_aborts_init(driver):
    driver.recorder_reset(1)
    assert driver.sh_drv_init()!=0
    assert history(driver)==[(1,0x40),(2,0)]
