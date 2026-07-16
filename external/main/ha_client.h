#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief  Start the Home Assistant client.
 *
 * Creates the entity cache mutex and the command queue, registers the UI
 * action sink, and spawns the worker task. Returns immediately — the worker
 * waits for WiFi on its own.
 *
 * The worker owns all HTTP: it re-renders one Jinja template per poll to
 * discover entities and read their states in a single request, and drains
 * queued on/off commands as they arrive. Entity IDs are never hardcoded;
 * everything comes from CONFIG_HA_CLIENT_* and the server's response.
 *
 * @return ESP_OK, or ESP_ERR_NO_MEM / ESP_FAIL if a primitive or the task
 *         could not be created.
 */
esp_err_t ha_client_init(void);

#ifdef __cplusplus
}
#endif
