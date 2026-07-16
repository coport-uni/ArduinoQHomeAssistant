#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Which tab an entity belongs on, and how its row is drawn. */
typedef enum {
    UI_HA_LIGHT,    /* toggle row on the Lights tab  */
    UI_HA_SWITCH,   /* toggle row on the Switch tab  */
    UI_HA_SENSOR,   /* read-only row on the Sensor tab */
} ui_ha_kind_t;

/** Action requested when an on-screen toggle is flipped. */
typedef enum {
    UI_HA_ACTION_ON,
    UI_HA_ACTION_OFF,
} ui_ha_action_t;

/**
 * One entity's display state.
 *
 * All string members are borrowed for the duration of the ui_ha_replace()
 * call only; the UI copies whatever it needs to keep.
 */
typedef struct {
    ui_ha_kind_t kind;
    const char  *name;       /* friendly name, e.g. "Living Room" */
    bool         available;  /* false when HA reports unavailable/unknown */
    bool         is_on;      /* LIGHT / SWITCH: relay state */
    const char  *value;      /* SENSOR: state text, e.g. "21.4" */
    const char  *unit;       /* SENSOR: unit, e.g. "°C"; may be "" */
} ui_ha_entity_t;

/**
 * Callback invoked on the LVGL task when a toggle is flipped by touch.
 *
 * It must NOT block (no HTTP, no long work) — it only forwards the request
 * to a worker, typically by posting to a queue.
 *
 * @param  idx     Index into the array last passed to ui_ha_replace().
 * @param  action  Requested state.
 */
typedef void (*ui_ha_action_cb_t)(int idx, ui_ha_action_t action);

/**
 * @brief  Build the tabview shell and the status footer.
 *
 * Must be called inside bsp_display_lock() / bsp_display_unlock(). Tabs are
 * added later by ui_ha_replace() once entities are known.
 */
void ui_create(void);

/**
 * @brief  Register the toggle action sink.
 *
 * The stored callback is invoked on the LVGL task whenever a toggle is
 * flipped by touch. Programmatic updates from ui_ha_replace() never fire it.
 */
void ui_ha_set_action_cb(ui_ha_action_cb_t cb);

/**
 * @brief  Replace the whole displayed entity set in one shot.
 *
 * Rebuilds the tabs when the entity set's shape changed (count, kind, or any
 * name); otherwise updates the existing rows in place. Publish the full set
 * once per poll rather than per entity — one lock, one redraw.
 *
 * Safe to call from any task; takes the LVGL lock internally.
 */
void ui_ha_replace(const ui_ha_entity_t *ents, int count);

/**
 * @brief  Update the footer status line.
 *
 * @param  color_hex  0xRRGGBB, so callers need not include lvgl.h.
 */
void ui_ha_set_status(const char *msg, uint32_t color_hex);

/** @brief  Move to the next / previous tab. Wraps around. */
void ui_select_next_tab(void);
void ui_select_prev_tab(void);

#ifdef __cplusplus
}
#endif
