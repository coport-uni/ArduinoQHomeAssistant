#include "ui.h"

#include <stdint.h>
#include <string.h>

#include "esp_log.h"
#include "bsp/esp-box-3.h"
#include "lvgl.h"

#include "sdkconfig.h"

static const char *TAG = "ui";

#define ENT_NAME_CAP    32
#define UI_LOCK_MS      50
#define UI_MAX_ENTS     CONFIG_HA_CLIENT_MAX_ENTITIES
#define ROW_H           34
#define NAME_W          200

#define COLOR_OK        lv_color_hex(0x06D6A0)
#define COLOR_MUTED     lv_color_hex(0x9CA3AF)
#define COLOR_BG        lv_color_hex(0x0A0E27)

typedef struct {
    lv_obj_t     *lbl_name;
    lv_obj_t     *sw;         /* LIGHT / SWITCH only */
    lv_obj_t     *lbl_value;  /* SENSOR only */
    ui_ha_kind_t  kind;
    char          name[ENT_NAME_CAP];
} entity_ui_t;

static lv_obj_t         *s_tabview;
static lv_obj_t         *s_lbl_status;
static entity_ui_t       s_ent_ui[UI_MAX_ENTS];
static int               s_ent_ui_count;
static ui_ha_action_cb_t s_action_cb;

#define UI_WITH_LOCK(BLOCK)                          \
    do {                                             \
        if (bsp_display_lock(UI_LOCK_MS)) {          \
            BLOCK;                                   \
            bsp_display_unlock();                    \
        }                                            \
    } while (0)

/* ---------------------- events ---------------------- */

/* Only touch reaches this. LVGL toggles LV_STATE_CHECKED and sends
 * VALUE_CHANGED from its LV_EVENT_RELEASED handler (lv_obj.c), whereas the
 * lv_obj_add_state / lv_obj_remove_state calls in apply_entity() go straight
 * to style bookkeeping and send nothing. So a poll refreshing a row cannot
 * loop back in here and re-issue the command it just observed. */
static void on_switch_changed(lv_event_t *e)
{
    lv_obj_t *sw = lv_event_get_target_obj(e);
    int idx = (int)(intptr_t)lv_event_get_user_data(e);

    if (!s_action_cb || idx < 0 || idx >= s_ent_ui_count) {
        return;
    }
    bool on = lv_obj_has_state(sw, LV_STATE_CHECKED);
    s_action_cb(idx, on ? UI_HA_ACTION_ON : UI_HA_ACTION_OFF);
}

/* ---------------------- row builders ---------------------- */

static lv_obj_t *make_row(lv_obj_t *tab)
{
    lv_obj_t *row = lv_obj_create(tab);
    lv_obj_set_size(row, lv_pct(100), ROW_H);
    lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(row, 0, 0);
    lv_obj_set_style_pad_all(row, 0, 0);
    /* The row must not compete with the tab page for scroll gestures. */
    lv_obj_remove_flag(row, LV_OBJ_FLAG_SCROLLABLE);
    return row;
}

/* Black, not white: the tab pages keep the LVGL theme's light background, so
 * only the footer sits on the dark screen colour. */
static void build_name_label(lv_obj_t *row, entity_ui_t *eu)
{
    eu->lbl_name = lv_label_create(row);
    lv_label_set_text(eu->lbl_name, "");
    lv_label_set_long_mode(eu->lbl_name, LV_LABEL_LONG_DOT);
    lv_obj_set_width(eu->lbl_name, NAME_W);
    lv_obj_set_style_text_color(eu->lbl_name, lv_color_black(), 0);
    lv_obj_align(eu->lbl_name, LV_ALIGN_LEFT_MID, 0, 0);
}

static void build_toggle_row(lv_obj_t *tab, entity_ui_t *eu, int idx)
{
    lv_obj_t *row = make_row(tab);
    build_name_label(row, eu);

    eu->sw = lv_switch_create(row);
    lv_obj_set_size(eu->sw, 46, 24);
    lv_obj_align(eu->sw, LV_ALIGN_RIGHT_MID, 0, 0);
    lv_obj_set_style_bg_color(eu->sw, COLOR_OK,
                              LV_PART_INDICATOR | LV_STATE_CHECKED);
    lv_obj_add_event_cb(eu->sw, on_switch_changed, LV_EVENT_VALUE_CHANGED,
                        (void *)(intptr_t)idx);
}

static void build_sensor_row(lv_obj_t *tab, entity_ui_t *eu)
{
    lv_obj_t *row = make_row(tab);
    build_name_label(row, eu);

    eu->lbl_value = lv_label_create(row);
    lv_label_set_text(eu->lbl_value, "--");
    lv_obj_set_style_text_color(eu->lbl_value, lv_color_black(), 0);
    lv_obj_align(eu->lbl_value, LV_ALIGN_RIGHT_MID, 0, 0);
}

static void apply_entity(entity_ui_t *eu, const ui_ha_entity_t *e)
{
    if (eu->lbl_name) {
        lv_label_set_text(eu->lbl_name, e->name ? e->name : "?");
        lv_obj_set_style_text_color(
            eu->lbl_name, e->available ? lv_color_black() : COLOR_MUTED, 0);
    }
    if (eu->sw) {
        if (e->is_on) {
            lv_obj_add_state(eu->sw, LV_STATE_CHECKED);
        } else {
            lv_obj_remove_state(eu->sw, LV_STATE_CHECKED);
        }
        /* An unavailable entity still draws, greyed out, so a device that
         * dropped off HA keeps its row instead of silently vanishing. */
        if (e->available) {
            lv_obj_remove_state(eu->sw, LV_STATE_DISABLED);
        } else {
            lv_obj_add_state(eu->sw, LV_STATE_DISABLED);
        }
    }
    if (eu->lbl_value) {
        if (!e->available || !e->value) {
            lv_label_set_text(eu->lbl_value, "--");
        } else {
            const char *unit = e->unit ? e->unit : "";
            lv_label_set_text_fmt(eu->lbl_value, "%s%s%s", e->value,
                                  unit[0] ? " " : "", unit);
        }
    }
}

/* ---------------------- tabview lifecycle ---------------------- */

static bool topology_changed(const ui_ha_entity_t *ents, int count)
{
    if (count != s_ent_ui_count) {
        return true;
    }
    for (int i = 0; i < count; i++) {
        if (ents[i].kind != s_ent_ui[i].kind) {
            return true;
        }
        const char *name = ents[i].name ? ents[i].name : "";
        if (strncmp(name, s_ent_ui[i].name, sizeof(s_ent_ui[i].name)) != 0) {
            return true;
        }
    }
    return false;
}

static void create_empty_tabview(void)
{
    s_tabview = lv_tabview_create(lv_scr_act());
    lv_obj_set_size(s_tabview, 320, 220);
    lv_obj_align(s_tabview, LV_ALIGN_TOP_LEFT, 0, 0);
    lv_tabview_set_tab_bar_size(s_tabview, 30);
}

static lv_obj_t *add_tab(const char *title)
{
    lv_obj_t *tab = lv_tabview_add_tab(s_tabview, title);
    lv_obj_set_style_pad_all(tab, 4, 0);
    lv_obj_set_flex_flow(tab, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(tab, 2, 0);
    return tab;
}

static void add_message_tab(const char *text)
{
    lv_obj_t *tab = add_tab("HA");
    lv_obj_t *lbl = lv_label_create(tab);
    lv_label_set_text(lbl, text);
    lv_obj_set_style_text_color(lbl, lv_color_black(), 0);
}

/* Pull the status footer back above the tabview — lv_obj_delete + create
 * resets z-order. */
static void restore_status_z_order(void)
{
    if (s_lbl_status) {
        lv_obj_move_foreground(s_lbl_status);
    }
}

static void rebuild_tabs(const ui_ha_entity_t *ents, int count)
{
    if (s_tabview) {
        lv_obj_delete(s_tabview);
        s_tabview = NULL;
    }
    memset(s_ent_ui, 0, sizeof(s_ent_ui));
    s_ent_ui_count = 0;

    create_empty_tabview();

    if (count <= 0) {
        add_message_tab("no entities");
        restore_status_z_order();
        return;
    }

    static const struct {
        ui_ha_kind_t kind;
        const char  *title;
    } TABS[] = {
        { UI_HA_LIGHT,  "Lights" },
        { UI_HA_SWITCH, "Switch" },
        { UI_HA_SENSOR, "Sensor" },
    };

    int n = count > UI_MAX_ENTS ? UI_MAX_ENTS : count;

    for (size_t t = 0; t < sizeof(TABS) / sizeof(TABS[0]); t++) {
        bool any = false;
        for (int i = 0; i < n && !any; i++) {
            any = (ents[i].kind == TABS[t].kind);
        }
        /* A kind with no entities gets no tab at all — an empty "Sensor"
         * tab would burn a slot on the 320px bar for nothing. */
        if (!any) {
            continue;
        }

        lv_obj_t *tab = add_tab(TABS[t].title);
        for (int i = 0; i < n; i++) {
            if (ents[i].kind != TABS[t].kind) {
                continue;
            }
            entity_ui_t *eu = &s_ent_ui[i];
            eu->kind = ents[i].kind;
            strncpy(eu->name, ents[i].name ? ents[i].name : "?",
                    sizeof(eu->name) - 1);
            if (ents[i].kind == UI_HA_SENSOR) {
                build_sensor_row(tab, eu);
            } else {
                /* idx is the caller's array index, which the client maps
                 * back to an entity_id. */
                build_toggle_row(tab, eu, i);
            }
        }
    }
    s_ent_ui_count = n;

    restore_status_z_order();
}

/* ---------------------- public API ---------------------- */

void ui_create(void)
{
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, COLOR_BG, 0);

    create_empty_tabview();
    add_message_tab("starting...");

    s_lbl_status = lv_label_create(scr);
    lv_label_set_text(s_lbl_status, "starting...");
    lv_obj_set_style_text_color(s_lbl_status, COLOR_MUTED, 0);
    lv_obj_set_width(s_lbl_status, 320);
    lv_label_set_long_mode(s_lbl_status, LV_LABEL_LONG_DOT);
    lv_obj_align(s_lbl_status, LV_ALIGN_BOTTOM_LEFT, 4, -2);

    ESP_LOGI(TAG, "ui ready");
}

void ui_ha_set_action_cb(ui_ha_action_cb_t cb)
{
    s_action_cb = cb;
}

void ui_ha_replace(const ui_ha_entity_t *ents, int count)
{
    if (!ents || count < 0) {
        return;
    }
    UI_WITH_LOCK({
        if (topology_changed(ents, count)) {
            rebuild_tabs(ents, count);
        }
        int n = count > UI_MAX_ENTS ? UI_MAX_ENTS : count;
        for (int i = 0; i < n; i++) {
            apply_entity(&s_ent_ui[i], &ents[i]);
        }
    });
}

void ui_ha_set_status(const char *msg, uint32_t color_hex)
{
    UI_WITH_LOCK({
        if (s_lbl_status) {
            lv_label_set_text(s_lbl_status, msg ? msg : "");
            lv_obj_set_style_text_color(s_lbl_status,
                                        lv_color_hex(color_hex), 0);
        }
    });
}

void ui_select_next_tab(void)
{
    UI_WITH_LOCK({
        if (s_tabview) {
            uint32_t cnt = lv_tabview_get_tab_count(s_tabview);
            if (cnt > 0) {
                uint32_t cur = lv_tabview_get_tab_active(s_tabview);
                lv_tabview_set_active(s_tabview, (cur + 1) % cnt, LV_ANIM_OFF);
            }
        }
    });
}

void ui_select_prev_tab(void)
{
    UI_WITH_LOCK({
        if (s_tabview) {
            uint32_t cnt = lv_tabview_get_tab_count(s_tabview);
            if (cnt > 0) {
                uint32_t cur = lv_tabview_get_tab_active(s_tabview);
                lv_tabview_set_active(s_tabview, (cur + cnt - 1) % cnt,
                                      LV_ANIM_OFF);
            }
        }
    });
}
