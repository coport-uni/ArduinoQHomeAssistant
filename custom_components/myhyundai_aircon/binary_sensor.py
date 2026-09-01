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
    """Add the device-connected binary sensor."""
    async_add_entities(
        [MyHyundaiConnectedSensor(entry.runtime_data.coordinator, entry)]
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
