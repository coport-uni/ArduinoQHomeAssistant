"""Connectivity coordinator for the myhyundai_aircon integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .adb_client import AdbClient, AdbClientError
from .const import COORDINATOR_INTERVAL_S, DOMAIN, RECONNECT_BACKOFF_S

_LOGGER = logging.getLogger(__name__)


class MyHyundaiCoordinator(DataUpdateCoordinator[bool]):
    """Poll ADB reachability and reconnect with staged backoff.

    The coordinator's data is a single boolean: whether the Android
    device currently answers over ADB. While disconnected, the poll
    interval walks the spec §10.3 backoff ladder instead of the
    normal cadence, and the last ladder step repeats until the
    device returns.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AdbClient,
    ) -> None:
        """Wire the coordinator to one config entry and its client."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=COORDINATOR_INTERVAL_S),
        )
        self.client = client
        self._backoff_index = 0

    async def _async_update_data(self) -> bool:
        """Check the session with a no-op shell, reconnecting if dead.

        Raises:
            UpdateFailed: If the device stays unreachable; the poll
                interval is moved along the backoff ladder first.
        """
        if self.client.is_connected:
            try:
                await self.client.async_shell("echo ok")
            except AdbClientError:
                _LOGGER.debug("ADB session dropped; will reconnect")
            else:
                self._reset_backoff()
                return True
        try:
            await self.client.async_connect()
        except AdbClientError as err:
            delay = RECONNECT_BACKOFF_S[self._backoff_index]
            self._backoff_index = min(
                self._backoff_index + 1, len(RECONNECT_BACKOFF_S) - 1
            )
            self.update_interval = timedelta(seconds=delay)
            raise UpdateFailed(
                f"device unreachable, retrying in {delay} s: {err}"
            ) from err
        self._reset_backoff()
        return True

    def _reset_backoff(self) -> None:
        """Return to the normal poll cadence after a good check."""
        self._backoff_index = 0
        self.update_interval = timedelta(seconds=COORDINATOR_INTERVAL_S)
