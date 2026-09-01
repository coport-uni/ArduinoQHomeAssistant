"""Aircon switch entity for myhyundai_aircon (spec §6.1)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AIRCON_MAX_MINUTES,
    DEFAULT_AIRCON_MAX_MINUTES,
    SEQUENCE_AIRCON_OFF,
    SEQUENCE_AIRCON_ON,
)
from .entity import MyHyundaiEntity
from .executor import SequenceError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the aircon switch for the config entry."""
    async_add_entities(
        [MyHyundaiAirconSwitch(entry.runtime_data.coordinator, entry)]
    )


class MyHyundaiAirconSwitch(MyHyundaiEntity, SwitchEntity):
    """Optimistic switch that drives the widget sequences.

    The component cannot read the real climate state (spec §1.4),
    so the switch is assumed-state: ON reflects the last successful
    aircon_on and falls back to OFF when the vehicle-side maximum
    runtime elapses.
    """

    _attr_assumed_state = True
    _attr_name = "aircon"

    def __init__(self, coordinator, entry) -> None:
        """Set up the optimistic state and the auto-off timer slot."""
        super().__init__(coordinator, entry, "aircon")
        self._attr_is_on = False
        self._last_started: datetime | None = None
        self._expires_at: datetime | None = None
        self._cancel_auto_off = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the spec §6.1 diagnostic attributes."""
        return {
            "last_result": self.coordinator.last_result,
            "last_error_code": self.coordinator.last_error,
            "last_started": self._last_started,
            "expires_at": self._expires_at,
            "screen_checked": (
                self.coordinator.executor.last_screen_checked
                if self.coordinator.executor
                else ""
            ),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Run aircon_on; only a judged success turns the switch on.

        Raises:
            HomeAssistantError: With the sequence error code.
        """
        try:
            await self.coordinator.async_execute(SEQUENCE_AIRCON_ON)
        except SequenceError as err:
            raise HomeAssistantError(str(err)) from err
        self._attr_is_on = True
        self._last_started = dt_util.now()
        self._schedule_auto_off()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Run aircon_off, or just reset state if it is undefined.

        Spec §6.1: with no runnable aircon_off sequence the switch
        must still return to OFF locally, with a warning.

        Raises:
            HomeAssistantError: When a defined sequence fails.
        """
        if self._is_off_sequence_runnable():
            try:
                await self.coordinator.async_execute(SEQUENCE_AIRCON_OFF)
            except SequenceError as err:
                raise HomeAssistantError(str(err)) from err
        else:
            _LOGGER.warning(
                "aircon_off is not defined or incomplete; resetting"
                " the switch without commanding the vehicle"
            )
        self._reset_to_off()
        self.async_write_ha_state()

    def _is_off_sequence_runnable(self) -> bool:
        """Return whether the recipe can actually turn the AC off."""
        executor = self.coordinator.executor
        if executor is None:
            return False
        sequence = executor.recipe.sequences.get(SEQUENCE_AIRCON_OFF)
        return bool(
            sequence and sequence.steps and not sequence.has_placeholders
        )

    def _schedule_auto_off(self) -> None:
        """Arm the fall-back timer for the vehicle-side max runtime."""
        self._cancel_pending_auto_off()
        minutes = self.coordinator.config_entry.options.get(
            CONF_AIRCON_MAX_MINUTES, DEFAULT_AIRCON_MAX_MINUTES
        )
        self._expires_at = dt_util.now() + timedelta(minutes=minutes)

        @callback
        def _auto_off(_now: datetime) -> None:
            _LOGGER.info(
                "Auto-off: %d minutes elapsed since aircon_on",
                minutes,
            )
            self._cancel_auto_off = None
            self._reset_to_off()
            self.async_write_ha_state()

        self._cancel_auto_off = async_call_later(
            self.hass, timedelta(minutes=minutes), _auto_off
        )

    def _reset_to_off(self) -> None:
        """Return to OFF and disarm the auto-off timer."""
        self._cancel_pending_auto_off()
        self._attr_is_on = False
        self._expires_at = None

    def _cancel_pending_auto_off(self) -> None:
        if self._cancel_auto_off is not None:
            self._cancel_auto_off()
            self._cancel_auto_off = None

    async def async_will_remove_from_hass(self) -> None:
        """Disarm the timer when the entity goes away."""
        self._cancel_pending_auto_off()
