"""Shared entity base for myhyundai_aircon platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MyHyundaiCoordinator


class MyHyundaiEntity(CoordinatorEntity[MyHyundaiCoordinator]):
    """Base entity bound to the dedicated Android device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MyHyundaiCoordinator, entry, key: str
    ) -> None:
        """Derive unique ID and device info from the config entry."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.title,
            manufacturer="Hyundai (unofficial)",
            model="MyHyundai widget bridge",
        )
