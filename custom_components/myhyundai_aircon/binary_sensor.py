"""Connectivity binary sensor for myhyundai_aircon (spec §6.3)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import MyHyundaiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the connectivity and door-lock binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            MyHyundaiConnectedSensor(coordinator, entry),
            MyHyundaiDoorsLockedSensor(coordinator, entry),
            MyHyundaiClimateRunningSensor(coordinator, entry),
        ]
    )


class MyHyundaiConnectedSensor(MyHyundaiEntity, BinarySensorEntity):
    """Whether the Android device answers over ADB."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "device connected"

    def __init__(self, coordinator, entry) -> None:
        """Bind to the coordinator's connectivity result."""
        super().__init__(coordinator, entry, "device_connected")

    @property
    def available(self) -> bool:
        """Stay available so OFF can actually be shown."""
        return True

    @property
    def is_on(self) -> bool:
        """Return the outcome of the last connectivity poll."""
        return self.coordinator.last_update_success


class MyHyundaiDoorsLockedSensor(MyHyundaiEntity, BinarySensorEntity):
    """Door-lock state scraped from the widget's status text.

    ON means the widget reports 문잠김 (locked); unknown until the
    first scrape or when the marker is missing.
    """

    _attr_name = "doors locked"
    _attr_icon = "mdi:car-door-lock"

    def __init__(self, coordinator, entry) -> None:
        """Bind to the coordinator's scraped vehicle data."""
        super().__init__(coordinator, entry, "doors_locked")

    @property
    def is_on(self) -> bool | None:
        """Return the scraped lock state, or None when unknown."""
        return self.coordinator.vehicle_data.doors_locked


class MyHyundaiClimateRunningSensor(MyHyundaiEntity, BinarySensorEntity):
    """Real climate state, detected from the widget's glow aura.

    Unlike the assumed-state switch, this reflects what the widget
    actually shows: while remote climate runs, the app draws a blue
    aura around the car image, which pixel analysis of the poll
    screenshot detects (experiment of 2026-09-02: ON 0.015 glow
    fraction, OFF exactly 0).
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_name = "climate running"
    _attr_icon = "mdi:fan"

    def __init__(self, coordinator, entry) -> None:
        """Bind to the coordinator's glow detection result."""
        super().__init__(coordinator, entry, "climate_running")

    @property
    def is_on(self) -> bool | None:
        """Return the detected state, or None before the first poll."""
        return self.coordinator.climate_running

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the raw glow fraction for threshold tuning."""
        return {"glow_fraction": self.coordinator.glow_fraction}
