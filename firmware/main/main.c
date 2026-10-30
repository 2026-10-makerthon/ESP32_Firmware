#include <string.h>
#include <stdatomic.h>
#include "sdkconfig.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_gatt.h"
#include "host/ble_store.h"
#include "host/ble_sm.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "sh_device.h"
#include "adapters.h"
#include "power.h"
#include "sh_link.h"
#ifndef CONFIG_SH_SIMULATED_HAPTIC
#define CONFIG_SH_SIMULATED_HAPTIC 0
#endif

#define UUID(n) BLE_UUID128_INIT(0xd0,0x48,0x10,0x2c,0x7e,0x9b,0x21,0xa3,0x7c,0x4d,0x5a,0x6f,n,0x00,0x1f,0x8e)
static const ble_uuid128_t service_uuid=UUID(0),audio_uuid=UUID(1),control_uuid=UUID(2),event_uuid=UUID(3),caps_uuid=UUID(4);
static sh_device device;
static SemaphoreHandle_t guard;
static uint16_t connection=BLE_HS_CONN_HANDLE_NONE,audio_handle,event_handle;
static uint8_t own_addr_type;
static bool event_inflight;
static uint32_t notify_errors;
static uint16_t audio_offset;
static uint16_t offset_seq;
static uint16_t offset_stream;
static atomic_bool stopping;
static atomic_bool capture_quiescent, transport_quiescent, haptic_failed;
static bool authorized, pairing_open, pairing_boot_pending, pairing_connection;
static uint32_t pairing_started, connected_at;
static struct ble_npl_callout security_timer;
void ble_store_config_init(void);

static uint32_t now_ms(void) {return (uint32_t)(esp_timer_get_time()/1000);}
static void lock(void) {xSemaphoreTake(guard,portMAX_DELAY);}
static void unlock(void) {xSemaphoreGive(guard);}
static int known_peer(const ble_addr_t *peer) {
    ble_addr_t stored[CONFIG_BT_NIMBLE_MAX_BONDS]; int count = 0;
    if (ble_store_util_bonded_peers(stored, &count, CONFIG_BT_NIMBLE_MAX_BONDS)) return 0;
    for (int i = 0; i < count; ++i)
        if (stored[i].type == peer->type && !memcmp(stored[i].val, peer->val, 6)) return 1;
    return 0;
}
static int has_bond(void) {
    ble_addr_t stored[CONFIG_BT_NIMBLE_MAX_BONDS]; int count = 0;
    return !ble_store_util_bonded_peers(stored, &count, CONFIG_BT_NIMBLE_MAX_BONDS) && count > 0;
}
static bool pairing_allowed(void) {
    return sh_link_pairing_open(pairing_open,pairing_started,now_ms(),CONFIG_SH_PAIRING_SECONDS*1000U);
}
static int access_cb(uint16_t conn,uint16_t attr,struct ble_gatt_access_ctxt *ctxt,void *arg) {
    (void)conn;(void)attr;
    lock();bool allowed=authorized && !atomic_load(&stopping);unlock();
    if (!allowed) return BLE_ATT_ERR_INSUFFICIENT_AUTHEN;
    if(arg==(void*)1 && ctxt->op==BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint16_t length=OS_MBUF_PKTLEN(ctxt->om);uint8_t raw[20];
        if(length<8 || length>20) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        if(os_mbuf_copydata(ctxt->om,0,length,raw)) return BLE_ATT_ERR_UNLIKELY;
        lock();
        if (atomic_load(&stopping)) {unlock();return BLE_ATT_ERR_UNLIKELY;}
        sh_device_command(&device,raw,length,now_ms());sh_output_set(device.haptic.level);unlock();
        return 0; /* Event, rather than this ATT success, reports command execution. */
    }
    if(arg==(void*)2 && ctxt->op==BLE_GATT_ACCESS_OP_READ_CHR) {
        uint8_t caps[20];lock();sh_device_capabilities(&device,caps);unlock();
#if CONFIG_SH_SYNTHETIC_AUDIO
        caps[2]|=16;
#endif
        return os_mbuf_append(ctxt->om,caps,20)?BLE_ATT_ERR_INSUFFICIENT_RES:0;
    }
    return BLE_ATT_ERR_UNLIKELY;
}
static const struct ble_gatt_svc_def services[]={
    {.type=BLE_GATT_SVC_TYPE_PRIMARY,.uuid=&service_uuid.u,.characteristics=(struct ble_gatt_chr_def[]){
        {.uuid=&audio_uuid.u,.flags=BLE_GATT_CHR_F_NOTIFY,.val_handle=&audio_handle,.access_cb=access_cb},
        {.uuid=&control_uuid.u,.flags=BLE_GATT_CHR_F_WRITE|BLE_GATT_CHR_F_WRITE_ENC,.access_cb=access_cb,.arg=(void*)1},
        {.uuid=&event_uuid.u,.flags=BLE_GATT_CHR_F_INDICATE,.val_handle=&event_handle,.access_cb=access_cb},
        {.uuid=&caps_uuid.u,.flags=BLE_GATT_CHR_F_READ|BLE_GATT_CHR_F_READ_ENC,.access_cb=access_cb,.arg=(void*)2},{0}}},{0}};

static void advertise(void);
static int gap_cb(struct ble_gap_event *event,void *arg) {
    (void)arg;
    switch(event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if(event->connect.status) {advertise();break;}
        {
            struct ble_gap_conn_desc desc;
            if (ble_gap_conn_find(event->connect.conn_handle, &desc) ||
                !sh_link_admit(atomic_load(&stopping),pairing_allowed(),known_peer(&desc.peer_id_addr))) {
                ble_gap_terminate(event->connect.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
                break;
            }
            pairing_connection=!known_peer(&desc.peer_id_addr);
        }
        lock();connection=event->connect.conn_handle;
        uint32_t previous=device.session,session;
        do {session=esp_random();} while(!session || session==previous);
        sh_device_init(&device,session,sh_output_verified(),CONFIG_SH_SIMULATED_HAPTIC);
        sh_device_allow_prototype(&device,sh_output_prototype());
        event_inflight=false;audio_offset=0;authorized=false;connected_at=now_ms();unlock();
        ESP_LOGI("ble","connected; waiting for encrypted bonded link");
        if (ble_gap_security_initiate(event->connect.conn_handle)) {
            ble_gap_terminate(event->connect.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
            break;
        }
        {
            struct ble_gap_upd_params params={.itvl_min=12,.itvl_max=24,.latency=0,.supervision_timeout=200};
            ble_gap_update_params(event->connect.conn_handle,&params);
        }
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        lock();sh_device_disconnect(&device);sh_output_off();connection=BLE_HS_CONN_HANDLE_NONE;
        event_inflight=false;audio_offset=0;authorized=false;unlock();advertise();break;
    case BLE_GAP_EVENT_ENC_CHANGE: {
        struct ble_gap_conn_desc desc;
        bool found = !ble_gap_conn_find(event->enc_change.conn_handle, &desc);
        bool ok = found &&
            sh_link_authorize(atomic_load(&stopping),event->enc_change.status,pairing_connection,
                pairing_allowed(),desc.sec_state.encrypted,desc.sec_state.bonded,
                desc.sec_state.key_size,known_peer(&desc.peer_id_addr));
        lock();authorized=ok && !atomic_load(&stopping);unlock();
        if (!ok) {
            if (found && pairing_connection) ble_store_util_delete_peer(&desc.peer_id_addr);
            ble_gap_terminate(event->enc_change.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
        }
        else {pairing_connection=false;pairing_open=false;ESP_LOGI("ble", "bonded peer authorized; pairing window closed");}
        break;
    }
    case BLE_GAP_EVENT_REPEAT_PAIRING:
        /* Replacing keys requires the physical six-second startup gesture. */
        return BLE_GAP_REPEAT_PAIRING_IGNORE;
    case BLE_GAP_EVENT_SUBSCRIBE:
        lock();
        if (!authorized || atomic_load(&stopping)) {
            unlock();ble_gap_terminate(event->subscribe.conn_handle,BLE_ERR_REM_USER_CONN_TERM);break;
        }
        if(event->subscribe.attr_handle==audio_handle) device.audio_sub=event->subscribe.cur_notify;
        if(event->subscribe.attr_handle==event_handle) device.event_sub=event->subscribe.cur_indicate;
        sh_device_transport(&device,ble_att_mtu(event->subscribe.conn_handle),device.audio_sub,device.event_sub);
        sh_output_set(device.haptic.level);unlock();break;
    case BLE_GAP_EVENT_MTU:
        lock();device.mtu=event->mtu.value;unlock();break;
    case BLE_GAP_EVENT_NOTIFY_TX:
        if(event->notify_tx.indication && event->notify_tx.status!=0) {
            lock();event_inflight=false;unlock();
            if(event->notify_tx.status!=BLE_HS_EDONE) ble_gap_terminate(event->notify_tx.conn_handle,BLE_ERR_REM_USER_CONN_TERM);
        }
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE: advertise();break;
    default: break;
    }
    return 0;
}
static void advertise(void) {
    if (atomic_load(&stopping)) return;
    bool pairing = pairing_allowed();
    if (!pairing && !has_bond()) {
        ESP_LOGI("ble", "no saved peer; power off then hold 6s to pair");return;
    }
    struct ble_hs_adv_fields fields={0};
    fields.flags=BLE_HS_ADV_F_BREDR_UNSUP|(pairing?BLE_HS_ADV_F_DISC_GEN:0);
    fields.uuids128=(ble_uuid128_t*)&service_uuid;fields.num_uuids128=1;fields.uuids128_is_complete=1;
    int rc=ble_gap_adv_set_fields(&fields);
    if(rc) {ESP_LOGE("ble","adv fields %d",rc);return;}
    struct ble_hs_adv_fields response={0};const char *name=pairing?"SoundHaptic-pair":"SoundHaptic-v1";
    response.name=(uint8_t*)name;response.name_len=strlen(name);response.name_is_complete=1;
    ble_gap_adv_rsp_set_fields(&response);
    struct ble_gap_adv_params params={0};params.conn_mode=BLE_GAP_CONN_MODE_UND;params.disc_mode=BLE_GAP_DISC_MODE_GEN;
    rc=ble_gap_adv_start(own_addr_type,NULL,BLE_HS_FOREVER,&params,gap_cb,NULL);
    if(rc) ESP_LOGE("ble","adv start %d",rc);
}
static void on_sync(void) {
    if (pairing_boot_pending) {
        /* Explicit re-pairing replaces the previous owner's bond. */
        pairing_boot_pending=false;
        if (ble_store_clear()) {ESP_LOGE("ble", "cannot clear previous bond");return;}
        pairing_open=true;pairing_started=now_ms();
    }
    if(ble_hs_id_infer_auto(0,&own_addr_type)==0) advertise();
}
static void on_reset(int reason) {
    lock();sh_device_disconnect(&device);sh_output_off();connection=BLE_HS_CONN_HANDLE_NONE;event_inflight=false;authorized=false;unlock();
    ESP_LOGE("ble","stack reset %d",reason);
}
static void host_task(void *param) {(void)param;nimble_port_run();nimble_port_freertos_deinit();}
static void security_check(struct ble_npl_event *event) {
    (void)event;
    if (atomic_load(&stopping)) return;
    if (pairing_open && !pairing_allowed()) {
        pairing_open=false;
        ble_gap_adv_stop();
        ESP_LOGI("ble", "pairing window expired");
        if (connection==BLE_HS_CONN_HANDLE_NONE) advertise();
    }
    lock();uint16_t conn=connection;bool ready=authorized;uint32_t start=connected_at;unlock();
    if (conn!=BLE_HS_CONN_HANDLE_NONE && !ready &&
        ((pairing_connection && !pairing_allowed()) || (uint32_t)(now_ms()-start)>=10000))
        ble_gap_terminate(conn,BLE_ERR_REM_USER_CONN_TERM);
    ble_npl_callout_reset(&security_timer,ble_npl_time_ms_to_ticks32(500));
}
static void shutdown_device(void) {
    atomic_store(&stopping,true);
    lock();authorized=false;sh_device_disconnect(&device);sh_output_sleep();unlock();
    /* Let outstanding capture/notify calls finish before deinitializing BLE. */
    uint32_t start=now_ms();
    while ((!atomic_load(&capture_quiescent) || !atomic_load(&transport_quiescent)) &&
           (uint32_t)(now_ms()-start)<500)
        vTaskDelay(pdMS_TO_TICKS(5));
    if (!atomic_load(&capture_quiescent) || !atomic_load(&transport_quiescent)) {
        ESP_LOGE("power", "worker did not stop; forcing deep sleep");return;
    }
    ble_npl_callout_stop(&security_timer);
    int rc=nimble_port_stop();
    if (!rc) nimble_port_deinit();
    else ESP_LOGE("power", "BLE stop failed (%d); deep sleep will disable radio",rc);
}
static void scheduler_task(void *param) {
    (void)param;TickType_t wake=xTaskGetTickCount();
    for(;;) {
        if(atomic_load(&stopping)) vTaskSuspend(NULL);
        lock();sh_device_tick(&device,now_ms());sh_output_set(device.haptic.level);
        if(!sh_output_healthy() && (device.verified || device.prototype_output)) {
            device.verified=0;sh_device_allow_prototype(&device,0);
            sh_device_disconnect(&device);sh_output_off();atomic_store(&haptic_failed,true);
        }
        unlock();
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(5));
    }
}
static void capture_task(void *param) {
    (void)param;static int16_t pcm[320];static double normalized[320];
    for(;;) {
        if(atomic_load(&stopping)) {atomic_store(&capture_quiescent,true);vTaskSuspend(NULL);}
        lock();uint16_t rate=device.armed && device.profile==2?8000:16000;
        uint16_t stream=device.stream;uint32_t session=device.session;bool armed=device.armed;unlock();
        uint32_t first;size_t count=rate/50;
        esp_err_t err=sh_capture_read(rate,pcm,normalized,count,&first);
        if(atomic_load(&stopping)) {atomic_store(&capture_quiescent,true);vTaskSuspend(NULL);}
        if(err!=ESP_OK) {
            lock();sh_device_disconnect(&device);sh_output_off();uint16_t conn=connection;unlock();
            if(conn!=BLE_HS_CONN_HANDLE_NONE) ble_gap_terminate(conn,BLE_ERR_REM_USER_CONN_TERM);
            ESP_LOGE("capture","read failed: %s",esp_err_to_name(err));vTaskDelay(pdMS_TO_TICKS(100));continue;
        }
        lock();
        if(!atomic_load(&stopping) && session==device.session && stream==device.stream && armed==device.armed)
            sh_device_capture(&device,pcm,normalized,count,first);
        unlock();
    }
}
static void transport_task(void *param) {
    (void)param;uint8_t packet[244];
    for(;;) {
        if(atomic_load(&stopping)) {atomic_store(&transport_quiescent,true);vTaskSuspend(NULL);}
        lock();uint16_t conn=authorized?connection:BLE_HS_CONN_HANDLE_NONE;uint32_t session=device.session;
        bool failed=atomic_exchange(&haptic_failed,false);
        if((device.event_overflows || failed) && conn!=BLE_HS_CONN_HANDLE_NONE) {
            sh_output_off();unlock();ble_gap_terminate(conn,BLE_ERR_REM_USER_CONN_TERM);
            vTaskDelay(pdMS_TO_TICKS(5));continue;
        }
        int event_n=0,audio_n=0;
        if(conn!=BLE_HS_CONN_HANDLE_NONE && device.event_sub && !event_inflight) {
            event_n=sh_device_event_peek(&device,packet);if(event_n) event_inflight=true;
        }
        if(!event_n && conn!=BLE_HS_CONN_HANDLE_NONE && device.audio_sub && !device.event_count) {
            if(device.audio_count && (offset_seq!=device.audio[0].seq || offset_stream!=device.stream)) audio_offset=0;
            if(device.audio_count) {offset_seq=device.audio[0].seq;offset_stream=device.stream;}
            audio_n=sh_device_audio_packet(&device,audio_offset,packet);
        }
        unlock();
        if(event_n || audio_n) {
            struct os_mbuf *buffer=ble_hs_mbuf_from_flat(packet,event_n?event_n:audio_n);
            int rc=buffer?(event_n?ble_gatts_indicate_custom(conn,event_handle,buffer):
                                   ble_gatts_notify_custom(conn,audio_handle,buffer)):BLE_HS_ENOMEM;
            lock();
            if(conn==connection && session==device.session) {
                if(event_n) {
                    if(!rc) {
                        uint8_t first[20];int n=sh_device_event_peek(&device,first);
                        if(n==event_n && !memcmp(first,packet,n)) sh_device_event_pop(&device);
                    } else event_inflight=false;
                } else if(!rc && device.audio_count && device.audio[0].seq==offset_seq && device.stream==offset_stream) {
                    audio_offset+=(uint16_t)(audio_n-16);
                    if(audio_offset>=device.audio[0].bytes) {sh_device_audio_pop(&device);audio_offset=0;}
                }
                if(rc) notify_errors++;
            }
            unlock();
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
static void metrics_task(void *param) {
    (void)param;
    for(;;) {vTaskDelay(pdMS_TO_TICKS(1000));lock();
        ESP_LOGI("metrics","selected=%u dropped=%lu queued=%u events=%u notify_errors=%lu heap=%lu",
            device.seq,(unsigned long)device.dropped,device.audio_count,device.event_count,
            (unsigned long)notify_errors,(unsigned long)esp_get_minimum_free_heap_size());unlock();}
}
void app_main(void) {
    esp_err_t output_error=sh_output_init();
    if(output_error!=ESP_OK)
        ESP_LOGE("haptic","output initialization failed; haptics disabled, power button/audio remain available");
    sh_output_off();
    pairing_boot_pending=sh_power_wait_for_on();
    guard=xSemaphoreCreateMutex();
    if(!guard) {sh_output_off();ESP_ERROR_CHECK(ESP_ERR_NO_MEM);return;}
    sh_device_init(&device,1,sh_output_verified(),CONFIG_SH_SIMULATED_HAPTIC);
    sh_device_allow_prototype(&device,sh_output_prototype());
    esp_err_t err=nvs_flash_init();
    if(err==ESP_ERR_NVS_NO_FREE_PAGES || err==ESP_ERR_NVS_NEW_VERSION_FOUND) {ESP_ERROR_CHECK(nvs_flash_erase());err=nvs_flash_init();}
    ESP_ERROR_CHECK(err);ESP_ERROR_CHECK(nimble_port_init());
    ble_svc_gap_init();ble_svc_gatt_init();ble_svc_gap_device_name_set("SoundHaptic-v1");
    ble_hs_cfg.sync_cb=on_sync;ble_hs_cfg.reset_cb=on_reset;
    ble_hs_cfg.sm_io_cap=BLE_HS_IO_NO_INPUT_OUTPUT;
    ble_hs_cfg.sm_bonding=1;ble_hs_cfg.sm_sc=1;ble_hs_cfg.sm_mitm=0;
    ble_hs_cfg.sm_our_key_dist=BLE_SM_PAIR_KEY_DIST_ENC|BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist=BLE_SM_PAIR_KEY_DIST_ENC|BLE_SM_PAIR_KEY_DIST_ID;
    ble_store_config_init();
    ble_npl_callout_init(&security_timer,nimble_port_get_dflt_eventq(),security_check,NULL);
    ble_npl_callout_reset(&security_timer,ble_npl_time_ms_to_ticks32(500));
    int rc=ble_gatts_count_cfg(services);
    if(!rc) rc=ble_gatts_add_svcs(services);
    if(rc) {ESP_LOGE("ble","GATT initialization failed: %d",rc);sh_output_off();return;}
    ble_att_set_preferred_mtu(247);nimble_port_freertos_init(host_task);
    if(xTaskCreate(scheduler_task,"haptic",4096,NULL,6,NULL)!=pdPASS ||
       xTaskCreate(capture_task,"capture",6144,NULL,5,NULL)!=pdPASS ||
       xTaskCreate(transport_task,"transport",4096,NULL,4,NULL)!=pdPASS ||
       xTaskCreate(metrics_task,"metrics",3072,NULL,2,NULL)!=pdPASS) {
        sh_output_off();ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    }
    ESP_ERROR_CHECK(sh_power_start(shutdown_device));
}
