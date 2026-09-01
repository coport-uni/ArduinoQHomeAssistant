"""Diagnostic and vehicle sensors for myhyundai_aircon (spec §6.2).

The vehicle_* sensors come from the read-only widget scrape
(vehicle_data.py); they report unknown until the first poll and go
stale rather than unavailable when a scrape fails.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MyHyundaiCoordinator
from .entity import MyHyundaiEntity


@dataclass(frozen=True, kw_only=True)
class MyHyundaiSensorDescription(SensorEntityDescription):
    """Sensor description with a coordinator value getter."""

    value_fn: Callable[[MyHyundaiCoordinator], str | int | datetime | None]


SENSOR_DESCRIPTIONS: tuple[MyHyundaiSensorDescription, ...] = (
    MyHyundaiSensorDescription(
        key="last_result",
        name="last result",
        value_fn=lambda c: c.last_result,
    ),
    MyHyundaiSensorDescription(
        key="last_error",
        name="last error",
        value_fn=lambda c: c.last_error,
    ),
    MyHyundaiSensorDescription(
        key="last_notification",
        name="last notification",
        # The executor already truncates to 255 (state length cap).
        value_fn=lambda c: c.last_notification or "none",
    ),
    MyHyundaiSensorDescription(
        key="vehicle_battery",
        name="vehicle battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.vehicle_data.battery_pct,
    ),
    MyHyundaiSensorDescription(
        key="vehicle_range",
        name="vehicle range",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.vehicle_data.range_km,
    ),
    MyHyundaiSensorDescription(
        key="data_updated_at",
        name="data updated at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.vehicle_data.updated_at,
    ),
    MyHyundaiSensorDescription(
        key="app_version",
        name="app version",
        value_fn=lambda c: c.app_version,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the diagnostic sensors for the config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MyHyundaiSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class MyHyundaiSensor(MyHyundaiEntity, SensorEntity):
    """A read-only view onto one coordinator result field."""

    entity_description: MyHyundaiSensorDescription

    def __init__(
        self,
        coordinator: MyHyundaiCoordinator,
        entry,
        description: MyHyundaiSensorDescription,
    ) -> None:
        """Bind the sensor to its description."""
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | datetime | None:
        """Return the described coordinator field."""
        return self.entity_description.value_fn(self.coordinator)
