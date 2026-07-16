#include "ha_client.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "esp_http_client.h"
#include "esp_log.h"

#include "cJSON.h"

#include "sdkconfig.h"

#include "network.h"
#include "ui.h"

static const char *TAG = "ha_client";

#define HA_ENTITY_ID_CAP    64
#define HA_NAME_CAP         32
#define HA_VALUE_CAP        16
#define HA_UNIT_CAP         8
#define HA_MAX_ENTS         CONFIG_HA_CLIENT_MAX_ENTITIES

#define TEMPLATE_CAP        512
#define HTTP_TIMEOUT_MS     8000
#define BUF_INIT            2048
#define BUF_MAX             8192
#define CMD_QUEUE_LEN       8
#define MAX_TSV_FIELDS      5

#define COL_OK              0x06D6A0
#define COL_WARN            0xFFD166
#define COL_MUTED           0x9CA3AF
#define COL_PINK            0xEF476F

typedef enum {
    DOM_LIGHT,
    DOM_SWITCH,
    DOM_SENSOR,
    DOM_COUNT,
} domain_t;

typedef struct {
    char     entity_id[HA_ENTITY_ID_CAP];
    char     name[HA_NAME_CAP];
    domain_t domain;
    bool     available;
    bool     is_on;                  /* LIGHT / SWITCH */
    char     value[HA_VALUE_CAP];    /* SENSOR */
    char     unit[HA_UNIT_CAP];      /* SENSOR */
} ha_entity_t;

/* The entity_id is resolved on the LVGL task at enqueue time rather than
 * carried as an index: by the time the worker drains the queue it may have
 * re-polled and reshuffled the cache, and a stale index would switch the
 * wrong device. */
typedef struct {
    char entity_id[HA_ENTITY_ID_CAP];
    bool turn_on;
} ha_cmd_t;

typedef struct {
    char  *buf;
    size_t len;
    size_t cap;
} resp_buf_t;

/* s_ents is the only state shared across tasks: the worker writes it, and
 * on_ui_action reads it from the LVGL task. s_mtx guards it and is held for
 * microseconds at a time — never across a ui_* call, which would take the
 * LVGL lock and invert the lock order against on_ui_action. */
static SemaphoreHandle_t s_mtx;
static QueueHandle_t     s_cmd_q;
static ha_entity_t       s_ents[HA_MAX_ENTS];
static int               s_ents_count;

/* Worker-task-only scratch. Static rather than stack: together these are
 * ~7 KB, and the worker's stack also nests esp_http_client and cJSON. */
static ha_entity_t    s_parsed[HA_MAX_ENTS];
static ha_entity_t    s_snap[HA_MAX_ENTS];
static ui_ha_entity_t s_view[HA_MAX_ENTS];

/* ---------------------- response buffer ---------------------- */

static esp_err_t buf_ensure(resp_buf_t *r, size_t need)
{
    if (need <= r->cap) {
        return ESP_OK;
    }
    if (need > BUF_MAX) {
        return ESP_FAIL;
    }
    size_t cap = r->cap ? r->cap : BUF_INIT;
    while (cap < need) {
        cap *= 2;
    }
    if (cap > BUF_MAX) {
        cap = BUF_MAX;
    }
    char *p = realloc(r->buf, cap);
    if (!p) {
        return ESP_ERR_NO_MEM;
    }
    r->buf = p;
    r->cap = cap;
    return ESP_OK;
}

static esp_err_t http_event(esp_http_client_event_t *evt)
{
    if (evt->event_id != HTTP_EVENT_ON_DATA || evt->data_len <= 0) {
        return ESP_OK;
    }
    resp_buf_t *r = (resp_buf_t *)evt->user_data;
    if (!r) {
        return ESP_OK;
    }
    if (buf_ensure(r, r->len + (size_t)evt->data_len + 1) != ESP_OK) {
        ESP_LOGW(TAG, "response buffer hit cap %d", BUF_MAX);
        return ESP_OK;
    }
    memcpy(r->buf + r->len, evt->data, (size_t)evt->data_len);
    r->len += (size_t)evt->data_len;
    r->buf[r->len] = '\0';
    return ESP_OK;
}

/* ---------------------- HTTP ---------------------- */

static void make_url(char *out, size_t cap, const char *path)
{
    const char *base = CONFIG_HA_CLIENT_SERVER_URL;
    size_t bl = strlen(base);
    while (bl > 0 && base[bl - 1] == '/') {
        bl--;
    }
    snprintf(out, cap, "%.*s%s", (int)bl, base, path);
}

/* Perform one authenticated request. `body` NULL sends no payload. The caller
 * owns resp->buf and must free it. */
static esp_err_t ha_request(esp_http_client_method_t method, const char *path,
                            const char *body, resp_buf_t *resp,
                            int *out_status)
{
    char url[256];
    make_url(url, sizeof(url), path);

    esp_http_client_config_t cfg = {
        .url           = url,
        .method        = method,
        .timeout_ms    = HTTP_TIMEOUT_MS,
        .event_handler = http_event,
        .user_data     = resp,
    };
    esp_http_client_handle_t cli = esp_http_client_init(&cfg);
    if (!cli) {
        return ESP_FAIL;
    }

    /* CONFIG_HA_CLIENT_TOKEN is a string literal, so sizeof gives the exact
     * room needed and this cannot truncate. */
    char auth[sizeof("Bearer ") + sizeof(CONFIG_HA_CLIENT_TOKEN)];
    snprintf(auth, sizeof(auth), "Bearer %s", CONFIG_HA_CLIENT_TOKEN);
    esp_http_client_set_header(cli, "Authorization", auth);

    if (body) {
        esp_http_client_set_header(cli, "Content-Type", "application/json");
        esp_http_client_set_post_field(cli, body, strlen(body));
    }

    esp_err_t err = esp_http_client_perform(cli);
    if (out_status) {
        *out_status = esp_http_client_get_status_code(cli);
    }
    esp_http_client_cleanup(cli);
    return err;
}

/* ---------------------- template ---------------------- */

/* One render returns every labelled entity plus its state, so discovery and
 * polling are the same request and the response stays ~1 KB. Fetching
 * /api/states instead would drag back every entity in the installation —
 * hundreds of KB — and truncate against BUF_MAX.
 *
 * Rendering one more than the cap lets the parser tell "exactly at the cap"
 * from "there are more", turning a silent truncation into a logged one.
 *
 * `states[e]` is guarded because a label can outlive the entity it was put
 * on, in which case the lookup yields nothing. */
static void build_template(char *out, size_t cap)
{
    snprintf(out, cap,
             "{%% for e in label_entities('%s') %%}"
             "{%% set s = states[e] %%}"
             "{%% if s and loop.index <= %d %%}"
             "{{s.domain}}\t{{e}}\t{{s.name}}\t{{s.state}}\t"
             "{{s.attributes.get('unit_of_measurement','')}}\n"
             "{%% endif %%}{%% endfor %%}",
             CONFIG_HA_CLIENT_LABEL, CONFIG_HA_CLIENT_MAX_ENTITIES + 1);
}

/* ---------------------- parsing ---------------------- */

static bool is_ascii_printable(const char *s)
{
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        if (*p < 0x20 || *p > 0x7E) {
            return false;
        }
    }
    return true;
}

/* Drop bytes the built-in font cannot draw. Used for units, where "°C" -> "C"
 * still reads correctly. */
static void copy_ascii(const char *src, char *out, size_t cap)
{
    size_t o = 0;
    for (const unsigned char *p = (const unsigned char *)src;
         *p && o + 1 < cap; p++) {
        if (*p >= 0x20 && *p <= 0x7E) {
            out[o++] = (char)*p;
        }
    }
    out[o] = '\0';
}

/* HA friendly names are free text and are often non-ASCII, but the only font
 * compiled in is montserrat_14, which covers ASCII. Rather than link a CJK
 * font and pay the flash for it, fall back to the entity_id's object part,
 * which HA always slugifies to ASCII: light.living_room -> "living room". */
static void pick_display_name(const char *entity_id, const char *friendly,
                              char *out, size_t cap)
{
    if (friendly && friendly[0] && is_ascii_printable(friendly)) {
        snprintf(out, cap, "%s", friendly);
        return;
    }
    const char *obj = strchr(entity_id, '.');
    obj = obj ? obj + 1 : entity_id;

    size_t i = 0;
    for (; obj[i] && i + 1 < cap; i++) {
        out[i] = (obj[i] == '_') ? ' ' : obj[i];
    }
    out[i] = '\0';
}

/* Split `line` in place on tabs. Returned pointers alias into `line`. */
static int split_tabs(char *line, char **fields, int max_fields)
{
    int n = 0;
    fields[n++] = line;
    for (char *p = line; *p && n < max_fields; p++) {
        if (*p == '\t') {
            *p = '\0';
            fields[n++] = p + 1;
        }
    }
    return n;
}

static void trim_cr(char *s)
{
    size_t n = strlen(s);
    while (n > 0 && (s[n - 1] == '\r' || s[n - 1] == '\n')) {
        s[--n] = '\0';
    }
}

static bool domain_from_name(const char *name, domain_t *out)
{
    if (strcmp(name, "light") == 0) {
        *out = DOM_LIGHT;
    } else if (strcmp(name, "switch") == 0) {
        *out = DOM_SWITCH;
    } else if (strcmp(name, "sensor") == 0) {
        *out = DOM_SENSOR;
    } else {
        return false;
    }
    return true;
}

static bool state_is_unavailable(const char *state)
{
    return strcmp(state, "unavailable") == 0 || strcmp(state, "unknown") == 0;
}

static const char *domain_label(domain_t d)
{
    switch (d) {
    case DOM_LIGHT:  return "lights";
    case DOM_SWITCH: return "switches";
    default:         return "sensors";
    }
}

/* Parse the rendered TSV into s_parsed, then publish it to s_ents under the
 * lock. `body` is modified in place. */
static void parse_response(char *body)
{
    int count = 0;
    int per_domain[DOM_COUNT] = { 0 };
    int skipped = 0;
    bool overflow = false;

    char *save = NULL;
    for (char *line = strtok_r(body, "\n", &save); line != NULL;
         line = strtok_r(NULL, "\n", &save)) {
        trim_cr(line);
        if (line[0] == '\0') {
            continue;
        }

        char *f[MAX_TSV_FIELDS];
        int nf = split_tabs(line, f, MAX_TSV_FIELDS);
        if (nf < 4) {
            continue;
        }
        domain_t dom;
        if (!domain_from_name(f[0], &dom)) {
            /* The label may sit on domains this screen has no row for, e.g.
             * a media_player. Not an error — just not ours. */
            ESP_LOGD(TAG, "skipping %s (domain %s)", f[1], f[0]);
            skipped++;
            continue;
        }
        if (count >= HA_MAX_ENTS) {
            overflow = true;
            break;
        }

        const char *entity_id = f[1];
        const char *friendly  = f[2];
        const char *state     = f[3];

        ha_entity_t *e = &s_parsed[count];
        memset(e, 0, sizeof(*e));
        e->domain = dom;
        snprintf(e->entity_id, sizeof(e->entity_id), "%s", entity_id);
        pick_display_name(entity_id, friendly, e->name, sizeof(e->name));
        e->available = !state_is_unavailable(state);

        if (dom == DOM_SENSOR) {
            copy_ascii(state, e->value, sizeof(e->value));
            if (nf >= 5) {
                copy_ascii(f[4], e->unit, sizeof(e->unit));
            }
        } else {
            e->is_on = (strcmp(state, "on") == 0);
        }

        per_domain[dom]++;
        count++;
    }

    if (overflow) {
        ESP_LOGW(TAG, "more than %d labelled entities; showing the first %d",
                 HA_MAX_ENTS, HA_MAX_ENTS);
    }
    if (skipped > 0) {
        ESP_LOGW(TAG, "%d labelled entities are in unsupported domains",
                 skipped);
    }

    xSemaphoreTake(s_mtx, portMAX_DELAY);
    memcpy(s_ents, s_parsed, sizeof(ha_entity_t) * (size_t)count);
    s_ents_count = count;
    xSemaphoreGive(s_mtx);

    ESP_LOGI(TAG, "parsed %d entities: %d %s, %d %s, %d %s", count,
             per_domain[DOM_LIGHT],  domain_label(DOM_LIGHT),
             per_domain[DOM_SWITCH], domain_label(DOM_SWITCH),
             per_domain[DOM_SENSOR], domain_label(DOM_SENSOR));
}

/* ---------------------- publish ---------------------- */

static ui_ha_kind_t kind_of(domain_t d)
{
    switch (d) {
    case DOM_LIGHT:  return UI_HA_LIGHT;
    case DOM_SWITCH: return UI_HA_SWITCH;
    default:         return UI_HA_SENSOR;
    }
}

/* Copies under the lock, then releases it before touching the UI: ui_ha_*
 * takes the LVGL lock, and on_ui_action runs with the LVGL lock already held
 * and wants s_mtx. Holding both here in the other order would deadlock. */
static void publish_to_ui(void)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    int n = s_ents_count;
    memcpy(s_snap, s_ents, sizeof(ha_entity_t) * (size_t)n);
    xSemaphoreGive(s_mtx);

    for (int i = 0; i < n; i++) {
        s_view[i].kind      = kind_of(s_snap[i].domain);
        s_view[i].name      = s_snap[i].name;
        s_view[i].available = s_snap[i].available;
        s_view[i].is_on     = s_snap[i].is_on;
        s_view[i].value     = s_snap[i].value;
        s_view[i].unit      = s_snap[i].unit;
    }
    ui_ha_replace(s_view, n);
}

/* ---------------------- API calls ---------------------- */

static esp_err_t poll_all(void)
{
    char tmpl[TEMPLATE_CAP];
    build_template(tmpl, sizeof(tmpl));

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return ESP_ERR_NO_MEM;
    }
    /* Built with cJSON, not snprintf: the template is full of quotes, tabs
     * and newlines that must be escaped exactly. */
    if (!cJSON_AddStringToObject(root, "template", tmpl)) {
        cJSON_Delete(root);
        return ESP_ERR_NO_MEM;
    }
    char *body = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!body) {
        return ESP_ERR_NO_MEM;
    }

    resp_buf_t resp = { 0 };
    int status = 0;
    esp_err_t err = ha_request(HTTP_METHOD_POST, "/api/template", body,
                               &resp, &status);
    cJSON_free(body);

    if (err != ESP_OK || status != 200) {
        /* HA returns the Jinja error in the body on 400; logging it is the
         * difference between a one-minute fix and an afternoon. */
        ESP_LOGW(TAG, "template: err=%s status=%d body=%.200s",
                 esp_err_to_name(err), status, resp.buf ? resp.buf : "");
        free(resp.buf);
        return err != ESP_OK ? err : ESP_FAIL;
    }

    /* The response is rendered text, not JSON. */
    parse_response(resp.buf);
    free(resp.buf);
    return ESP_OK;
}

/* Explicit turn_on / turn_off rather than toggle: a toggle issued while the
 * screen shows a stale state lands on the opposite of what the user asked
 * for. */
static esp_err_t send_command(const char *entity_id, bool turn_on)
{
    const char *dot = strchr(entity_id, '.');
    if (!dot) {
        ESP_LOGW(TAG, "malformed entity_id \"%s\"", entity_id);
        return ESP_ERR_INVALID_ARG;
    }

    char path[96];
    snprintf(path, sizeof(path), "/api/services/%.*s/turn_%s",
             (int)(dot - entity_id), entity_id, turn_on ? "on" : "off");

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return ESP_ERR_NO_MEM;
    }
    if (!cJSON_AddStringToObject(root, "entity_id", entity_id)) {
        cJSON_Delete(root);
        return ESP_ERR_NO_MEM;
    }
    char *body = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!body) {
        return ESP_ERR_NO_MEM;
    }

    resp_buf_t resp = { 0 };
    int status = 0;
    esp_err_t err = ha_request(HTTP_METHOD_POST, path, body, &resp, &status);
    cJSON_free(body);
    free(resp.buf);

    if (err != ESP_OK || status < 200 || status >= 300) {
        ESP_LOGW(TAG, "%s: err=%s status=%d", path, esp_err_to_name(err),
                 status);
        return err != ESP_OK ? err : ESP_FAIL;
    }
    ESP_LOGI(TAG, "%s ok", path);
    return ESP_OK;
}

static void handle_command(const ha_cmd_t *cmd)
{
    ui_ha_set_status("sending...", COL_WARN);

    if (send_command(cmd->entity_id, cmd->turn_on) != ESP_OK) {
        ui_ha_set_status("command failed", COL_PINK);
        /* Snap the optimistic toggle back to the last known truth. */
        publish_to_ui();
        return;
    }

    /* HA's service call returns once the state has settled, so re-reading
     * immediately confirms what actually happened rather than trusting the
     * toggle the user just flipped. */
    if (poll_all() == ESP_OK) {
        publish_to_ui();
        ui_ha_set_status("updated", COL_MUTED);
    } else {
        ui_ha_set_status("refresh failed", COL_PINK);
    }
}

/* ---------------------- UI action sink ---------------------- */

/* Runs on the LVGL task. Must not block: resolve the id and hand it off. */
static void on_ui_action(int idx, ui_ha_action_t action)
{
    if (!s_cmd_q || !s_mtx) {
        return;
    }
    ha_cmd_t cmd = { .turn_on = (action == UI_HA_ACTION_ON) };

    /* s_mtx is only ever held for a memcpy, so this effectively never waits;
     * the timeout is here so a touch callback can never stall the LVGL task. */
    if (xSemaphoreTake(s_mtx, pdMS_TO_TICKS(20)) != pdTRUE) {
        ESP_LOGW(TAG, "cache busy, dropping action");
        return;
    }
    bool ok = (idx >= 0 && idx < s_ents_count);
    if (ok) {
        snprintf(cmd.entity_id, sizeof(cmd.entity_id), "%s",
                 s_ents[idx].entity_id);
    }
    xSemaphoreGive(s_mtx);

    if (!ok) {
        return;
    }
    if (xQueueSend(s_cmd_q, &cmd, 0) != pdTRUE) {
        ESP_LOGW(TAG, "command queue full, dropping %s", cmd.entity_id);
    }
}

/* ---------------------- task ---------------------- */

static void ha_task(void *arg)
{
    (void)arg;

    if (strlen(CONFIG_HA_CLIENT_SERVER_URL) == 0) {
        ui_ha_set_status("set server URL (menuconfig)", COL_PINK);
        vTaskDelete(NULL);
        return;
    }
    if (strlen(CONFIG_HA_CLIENT_TOKEN) == 0) {
        /* The REST API takes a long-lived token only — a HA username and
         * password will not authenticate here. */
        ui_ha_set_status("set HA token (menuconfig)", COL_PINK);
        vTaskDelete(NULL);
        return;
    }
    if (strlen(CONFIG_HA_CLIENT_LABEL) == 0) {
        ui_ha_set_status("set HA label (menuconfig)", COL_PINK);
        vTaskDelete(NULL);
        return;
    }

    ui_ha_set_status("WiFi connecting...", COL_WARN);
    network_wait_connected(portMAX_DELAY);

    ui_ha_set_status("reading entities...", COL_WARN);
    while (poll_all() != ESP_OK) {
        ui_ha_set_status("HA unreachable", COL_PINK);
        vTaskDelay(pdMS_TO_TICKS(5000));
        if (!network_is_connected()) {
            network_wait_connected(portMAX_DELAY);
        }
        ui_ha_set_status("reading entities...", COL_WARN);
    }
    publish_to_ui();
    ui_ha_set_status("updated", COL_MUTED);

    const TickType_t period =
        pdMS_TO_TICKS(CONFIG_HA_CLIENT_POLL_INTERVAL_S * 1000);

    while (1) {
        ha_cmd_t cmd;
        /* The receive doubles as the poll timer: a queued command short-cuts
         * the wait, a timeout means it is time to refresh. */
        if (xQueueReceive(s_cmd_q, &cmd, period) == pdTRUE) {
            handle_command(&cmd);
        } else {
            if (!network_is_connected()) {
                ui_ha_set_status("WiFi lost...", COL_WARN);
                network_wait_connected(portMAX_DELAY);
                continue;
            }
            if (poll_all() == ESP_OK) {
                publish_to_ui();
                ui_ha_set_status("updated", COL_MUTED);
            } else {
                ui_ha_set_status("HA unreachable", COL_PINK);
            }
        }
    }
}

/* ---------------------- public API ---------------------- */

esp_err_t ha_client_init(void)
{
    s_mtx = xSemaphoreCreateMutex();
    if (!s_mtx) {
        return ESP_ERR_NO_MEM;
    }
    s_cmd_q = xQueueCreate(CMD_QUEUE_LEN, sizeof(ha_cmd_t));
    if (!s_cmd_q) {
        return ESP_ERR_NO_MEM;
    }
    ui_ha_set_action_cb(on_ui_action);

    /* 8 KB: the task nests esp_http_client and cJSON under poll_all() and
     * handle_command(). */
    BaseType_t ok = xTaskCreatePinnedToCore(ha_task, "ha_client", 8192, NULL,
                                            4, NULL, 0);
    return ok == pdPASS ? ESP_OK : ESP_FAIL;
}
