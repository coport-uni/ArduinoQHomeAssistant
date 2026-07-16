#include "network.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#include "esp_log.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include "sdkconfig.h"

static const char *TAG = "network";

#define NET_BIT_CONNECTED  BIT0

static EventGroupHandle_t s_event_group;
static volatile network_state_t s_state = NETWORK_STATE_IDLE;
static esp_netif_t *s_netif;
static bool s_disabled;  /* true when SSID is empty: skip bring-up */

static void on_wifi_event(void *arg, esp_event_base_t base,
                          int32_t id, void *data)
{
    (void)arg;
    (void)data;

    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "wifi started, connecting");
        s_state = NETWORK_STATE_CONNECTING;
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *e =
            (wifi_event_sta_disconnected_t *)data;
        ESP_LOGW(TAG, "disconnected, reason=%d", e ? e->reason : -1);
        s_state = NETWORK_STATE_DISCONNECTED;
        xEventGroupClearBits(s_event_group, NET_BIT_CONNECTED);
        /* esp_wifi reconnects on its own schedule; just request again. */
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "got IP " IPSTR, IP2STR(&e->ip_info.ip));
        s_state = NETWORK_STATE_CONNECTED;
        xEventGroupSetBits(s_event_group, NET_BIT_CONNECTED);
    }
}

static esp_err_t ensure_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES ||
        err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "nvs reinit (%s)", esp_err_to_name(err));
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    return err;
}

esp_err_t network_init(void)
{
    if (s_event_group == NULL) {
        s_event_group = xEventGroupCreate();
    }

    if (strlen(CONFIG_HA_CLIENT_WIFI_SSID) == 0) {
        ESP_LOGW(TAG, "CONFIG_HA_CLIENT_WIFI_SSID is empty; WiFi disabled");
        s_disabled = true;
        s_state = NETWORK_STATE_IDLE;
        return ESP_OK;
    }

    ESP_ERROR_CHECK(ensure_nvs());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, NULL, NULL));

    wifi_config_t wcfg = { 0 };
    strncpy((char *)wcfg.sta.ssid,
            CONFIG_HA_CLIENT_WIFI_SSID, sizeof(wcfg.sta.ssid) - 1);
    strncpy((char *)wcfg.sta.password,
            CONFIG_HA_CLIENT_WIFI_PASSWORD, sizeof(wcfg.sta.password) - 1);
    wcfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wcfg.sta.pmf_cfg.capable = true;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wcfg));
    ESP_LOGI(TAG, "starting wifi, ssid=\"%s\"", CONFIG_HA_CLIENT_WIFI_SSID);
    ESP_ERROR_CHECK(esp_wifi_start());

    return ESP_OK;
}

network_state_t network_get_state(void)
{
    return s_state;
}

bool network_is_connected(void)
{
    return s_state == NETWORK_STATE_CONNECTED;
}

void network_wait_connected(uint32_t timeout_ms)
{
    if (s_disabled || s_event_group == NULL) {
        return;
    }
    TickType_t ticks = (timeout_ms == UINT32_MAX)
        ? portMAX_DELAY
        : pdMS_TO_TICKS(timeout_ms);
    xEventGroupWaitBits(s_event_group, NET_BIT_CONNECTED,
                        pdFALSE, pdTRUE, ticks);
}
