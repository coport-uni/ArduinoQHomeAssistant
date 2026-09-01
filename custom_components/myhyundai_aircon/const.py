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
