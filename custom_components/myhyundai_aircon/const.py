"""Constants for the myhyundai_aircon integration."""

DOMAIN = "myhyundai_aircon"

CONF_ADBKEY_PATH = "adbkey_path"
CONF_BASELINE_SCREEN = "baseline_screen"
CONF_DEVICE_NAME = "device_name"

DEFAULT_ADBKEY_FILENAME = "myhyundai_aircon_adbkey"
DEFAULT_DEVICE_NAME = "myhyundai"
DEFAULT_PORT = 5555

# ADB transport timeouts. The connect value covers the TCP
# handshake plus the on-device RSA authorization exchange.
CONNECT_TIMEOUT_S = 10.0
AUTH_TIMEOUT_S = 10.0
SHELL_TIMEOUT_S = 15.0

# Connectivity poll cadence and the reconnect backoff ladder from
# spec §10.3 (the last value repeats until the device returns).
COORDINATOR_INTERVAL_S = 30
RECONNECT_BACKOFF_S = (5, 15, 45, 60)

CONF_RECIPE_FILE = "recipe_file"
DEFAULT_RECIPE_FILE = "default.json"

# Options-flow keys and defaults (spec §5.2). The notification wait
# limit lives in the recipe's await_notification steps, so it is
# not duplicated as an option.
CONF_AIRCON_MAX_MINUTES = "aircon_max_minutes"
CONF_BATTERY_FLOOR_PCT = "battery_floor_pct"
CONF_BATTERY_SENSOR = "battery_sensor"
CONF_COMMAND_MIN_GAP_SEC = "command_min_gap_sec"
CONF_COOLDOWN_SEC = "cooldown_sec"
CONF_DUMP_ON_FAILURE = "dump_on_failure"
CONF_RETRY_GAP_SEC = "retry_gap_sec"
CONF_RETRY_MAX = "retry_max"
CONF_SCREEN_CHECK_ENABLED = "screen_check_enabled"
CONF_SEQUENCE_TIMEOUT_SEC = "sequence_timeout_sec"
# Read-only widget scrape cadence; 0 disables the poll entirely.
CONF_VEHICLE_POLL_MINUTES = "vehicle_poll_minutes"

DEFAULT_AIRCON_MAX_MINUTES = 10
DEFAULT_BATTERY_FLOOR_PCT = 40
DEFAULT_COMMAND_MIN_GAP_SEC = 3
DEFAULT_COOLDOWN_SEC = 60
DEFAULT_RETRY_GAP_SEC = 30
DEFAULT_RETRY_MAX = 2
DEFAULT_SEQUENCE_TIMEOUT_SEC = 90
DEFAULT_VEHICLE_POLL_MINUTES = 15

SEQUENCE_AIRCON_OFF = "aircon_off"
SEQUENCE_AIRCON_ON = "aircon_on"

# Any string value still carrying this marker means the recipe has
# not been filled in from real-device dumps yet (spec §8.5).
PLACEHOLDER_MARKER = "_PLACEHOLDER"

# UI polling cadence for wait_node / wait_focus; a UI dump costs
# about one second on-device, so faster polling buys nothing
# (spec §10.4).
UI_POLL_INTERVAL_S = 1.0

SERVICE_CAPTURE_DUMP = "capture_dump"
SERVICE_RELOAD_RECIPE = "reload_recipe"
SERVICE_RUN_SEQUENCE = "run_sequence"

ATTR_IGNORE_GUARDS = "ignore_guards"
ATTR_LABEL = "label"
ATTR_SEQUENCE = "sequence"

EVENT_RESULT = "myhyundai_aircon_result"

DUMP_DIR_NAME = "myhyundai_aircon_dumps"
# XML + PNG pairs; 20 pairs keeps the eMMC safe (2 GB free).
DUMP_RETENTION_FILES = 40

# On-device scratch paths used while capturing dumps.
DEVICE_UI_XML_PATH = "/sdcard/myhyundai_aircon_ui.xml"
DEVICE_SCREENSHOT_PATH = "/sdcard/myhyundai_aircon_cap.png"

# Error codes from spec §9.3, plus E_UNKNOWN_SEQUENCE for a
# run_sequence call naming a key the recipe does not define.
ERR_RECIPE_INCOMPLETE = "E_RECIPE_INCOMPLETE"
ERR_COOLDOWN = "E_COOLDOWN"
ERR_MIN_GAP = "E_MIN_GAP"
ERR_BATTERY_LOW = "E_BATTERY_LOW"
ERR_DEVICE_OFFLINE = "E_DEVICE_OFFLINE"
ERR_SCREEN_MISMATCH = "E_SCREEN_MISMATCH"
ERR_SESSION_EXPIRED = "E_SESSION_EXPIRED"
ERR_UNKNOWN_SCREEN = "E_UNKNOWN_SCREEN"
ERR_TIMEOUT = "E_TIMEOUT"
ERR_VEHICLE_FAIL = "E_VEHICLE_FAIL"
ERR_UNKNOWN_SEQUENCE = "E_UNKNOWN_SEQUENCE"
