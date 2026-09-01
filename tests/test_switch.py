"""Unit tests for the aircon switch's optimistic state machine."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.myhyundai_aircon.const import (
    CONF_AIRCON_MAX_MINUTES,
    DOMAIN,
)
from custom_components.myhyundai_aircon.switch import (
    MyHyundaiAirconSwitch,
)


def _make_switch(
    hass: HomeAssistant, *, off_runnable: bool
) -> tuple[MyHyundaiAirconSwitch, MagicMock]:
    """Build a switch around a mocked coordinator."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_AIRCON_MAX_MINUTES: 10},
        unique_id="R3CR80H1GBN",
        title="myhyundai",
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.config_entry = entry
    coordinator.hass = hass
    coordinator.last_result = "unknown"
    coordinator.last_error = "none"
    coordinator.async_execute = AsyncMock(return_value={"result": "success"})
    if off_runnable:
        sequence = MagicMock(steps=(1,), has_placeholders=False)
    else:
        sequence = None
    coordinator.executor.recipe.sequences.get.return_value = sequence
    coordinator.executor.last_screen_checked = "840x2289"
    switch = MyHyundaiAirconSwitch(coordinator, entry)
    switch.hass = hass
    switch.entity_id = "switch.myhyundai_aircon"
    return switch, coordinator


async def test_turn_on_sets_state_and_auto_off(
    hass: HomeAssistant,
) -> None:
    """ON runs aircon_on; the auto-off timer reverts it (T10)."""
    switch, coordinator = _make_switch(hass, off_runnable=True)
    await switch.async_turn_on()
    coordinator.async_execute.assert_awaited_with("aircon_on")
    assert switch.is_on
    assert switch.extra_state_attributes["expires_at"] is not None

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
    await hass.async_block_till_done()
    assert not switch.is_on
    assert switch.extra_state_attributes["expires_at"] is None


async def test_turn_off_runs_off_sequence(
    hass: HomeAssistant,
) -> None:
    """OFF drives the widget when aircon_off is runnable."""
    switch, coordinator = _make_switch(hass, off_runnable=True)
    await switch.async_turn_on()
    await switch.async_turn_off()
    coordinator.async_execute.assert_awaited_with("aircon_off")
    assert not switch.is_on


async def test_turn_off_without_sequence_resets_locally(
    hass: HomeAssistant,
) -> None:
    """Without a runnable aircon_off the switch resets silently."""
    switch, coordinator = _make_switch(hass, off_runnable=False)
    await switch.async_turn_on()
    coordinator.async_execute.reset_mock()
    await switch.async_turn_off()
    coordinator.async_execute.assert_not_awaited()
    assert not switch.is_on
