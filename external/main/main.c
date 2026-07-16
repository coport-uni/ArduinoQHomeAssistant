#include "esp_log.h"

#include "bsp/esp-box-3.h"

#include "buttons_check.h"
#include "ha_client.h"
#include "network.h"
#include "ui.h"

static const char *TAG = "main";

static void on_config_pressed(void)
{
    ui_select_prev_tab();
}

static void on_mute_pressed(void)
{
    ui_select_next_tab();
}

void app_main(void)
{
    ESP_LOGI(TAG, "Home Assistant client starting");

    /* Init order mirrors the BOX-3 BSP contract: the shared I2C bus must
     * come up before the display (touch lives on it), the backlight is off
     * until explicitly turned on, and every lv_* call from app_main must be
     * wrapped in the BSP display lock. */
    ESP_ERROR_CHECK(bsp_i2c_init());
    bsp_display_start();
    bsp_display_backlight_on();

    bsp_display_lock(0);
    ui_create();
    bsp_display_unlock();

    /* The tabs are also swipeable — the BSP registers a touch indev — but the
     * physical buttons work with a finger already holding the board. */
    buttons_callbacks_t btn_cbs = {
        .on_config = on_config_pressed,
        .on_mute   = on_mute_pressed,
    };
    buttons_check_init(&btn_cbs);

    network_init();
    ESP_ERROR_CHECK(ha_client_init());

    ESP_LOGI(TAG, "init complete");
}
