"""The myhyundai_aircon integration.

Controls Hyundai remote climate by driving the MyHyundai home-screen
widget on a dedicated Android device over ADB TCP. This module wires
the config entry to the ADB client and the connectivity coordinator;
entity platforms arrive in a later implementation stage.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .adb_client import AdbClient
from .const import CONF_ADBKEY_PATH
from .coordinator import MyHyundaiCoordinator

type MyHyundaiConfigEntry = ConfigEntry[MyHyundaiCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: MyHyundaiConfigEntry
) -> bool:
    """Connect to the Android device and start connectivity polling.

    Raises:
        ConfigEntryNotReady: Via the coordinator's first refresh when
            the device is unreachable, so setup is retried.
    """
    client = AdbClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_ADBKEY_PATH],
    )
    coordinator = MyHyundaiCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MyHyundaiConfigEntry
) -> bool:
    """Close the ADB session when the entry is unloaded."""
    await entry.runtime_data.client.async_close()
    return True
