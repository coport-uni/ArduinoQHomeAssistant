#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    NETWORK_STATE_IDLE,
    NETWORK_STATE_CONNECTING,
    NETWORK_STATE_CONNECTED,
    NETWORK_STATE_DISCONNECTED,
} network_state_t;

/**
 * @brief  Bring up the WiFi STA stack non-blockingly.
 *
 * Initializes NVS, esp_netif, the default event loop and esp_wifi in
 * station mode using CONFIG_HA_CLIENT_WIFI_SSID /
 * CONFIG_HA_CLIENT_WIFI_PASSWORD, then keeps reconnecting on disconnect.
 * Returns immediately — the caller does not wait for association.
 *
 * If CONFIG_HA_CLIENT_WIFI_SSID is empty, this logs a warning and
 * returns ESP_OK without starting WiFi.
 */
esp_err_t       network_init(void);

/**
 * @brief  Return the current WiFi STA connection state.
 *
 * Safe to call from any task; reads a single word updated by the WiFi
 * event handler.
 *
 * @return One of the `NETWORK_STATE_*` enum values.
 */
network_state_t network_get_state(void);

/**
 * @brief  Convenience predicate: link is up and an IP has been acquired.
 *
 * @return true if connected, false otherwise.
 */
bool            network_is_connected(void);

/**
 * @brief  Block the caller until the link is up or the timeout expires.
 *
 * @param  timeout_ms  Maximum time to wait. 0 returns immediately.
 *                     UINT32_MAX waits forever.
 */
void            network_wait_connected(uint32_t timeout_ms);

#ifdef __cplusplus
}
#endif
