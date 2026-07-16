#include "buttons_check.h"

#include <stdint.h>

#include "esp_log.h"
#include "iot_button.h"
#include "bsp/esp-box-3.h"

static const char *TAG = "buttons";

static buttons_callbacks_t s_user_cbs;

static void on_short(void *handle, void *usr_data)
{
    (void)handle;
    int idx = (int)(intptr_t)usr_data;

    if (idx == BSP_BUTTON_CONFIG && s_user_cbs.on_config) {
        s_user_cbs.on_config();
    } else if (idx == BSP_BUTTON_MUTE && s_user_cbs.on_mute) {
        s_user_cbs.on_mute();
    }
}

esp_err_t buttons_check_init(const buttons_callbacks_t *cbs)
{
    if (cbs) {
        s_user_cbs = *cbs;
    }
    button_handle_t handles[BSP_BUTTON_NUM] = {0};
    int btn_cnt = 0;
    esp_err_t err = bsp_iot_button_create(handles, &btn_cnt, BSP_BUTTON_NUM);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "bsp_iot_button_create: %s", esp_err_to_name(err));
        return err;
    }
    ESP_LOGI(TAG, "registered %d buttons", btn_cnt);

    for (int i = 0; i < btn_cnt && i < BSP_BUTTON_NUM; i++) {
        if (!handles[i]) {
            continue;
        }
        iot_button_register_cb(handles[i], BUTTON_SINGLE_CLICK,
                               NULL, on_short, (void *)(intptr_t)i);
    }
    return ESP_OK;
}
