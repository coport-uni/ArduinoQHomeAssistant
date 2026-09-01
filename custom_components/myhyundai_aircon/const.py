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
