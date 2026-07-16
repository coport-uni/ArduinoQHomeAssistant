#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    void (*on_config)(void);   /* short press on BSP_BUTTON_CONFIG */
    void (*on_mute)(void);     /* short press on BSP_BUTTON_MUTE   */
} buttons_callbacks_t;

/**
 * @brief  Register short-press callbacks for the on-board CONFIG and MUTE
 *         buttons via the BSP iot_button driver.
 *
 * Spawns the BSP button task on first call. Callbacks fire from that task
 * (not an ISR) so they may take the LVGL lock and update widgets directly.
 * Passing NULL for either field in @p cbs disables that button.
 *
 * @param  cbs  Callbacks to install. The struct is copied, so the caller
 *              may pass a stack temporary. NULL leaves both buttons
 *              registered but inert.
 *
 * @return ESP_OK on success, or an esp_err_t from the underlying
 *         `bsp_iot_button_create` / `iot_button_register_cb` chain.
 */
esp_err_t buttons_check_init(const buttons_callbacks_t *cbs);

#ifdef __cplusplus
}
#endif
