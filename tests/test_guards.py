"""Unit tests for the coordinator's guards and retry ladder."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.myhyundai_aircon.const import (
    CONF_BATTERY_FLOOR_PCT,
    CONF_BATTERY_SENSOR,
    CONF_COMMAND_MIN_GAP_SEC,
    CONF_COOLDOWN_SEC,
    CONF_RETRY_GAP_SEC,
    DOMAIN,
    ERR_BATTERY_LOW,
    ERR_COOLDOWN,
    ERR_MIN_GAP,
    ERR_TIMEOUT,
    ERR_UNKNOWN_SCREEN,
    ERR_VEHICLE_FAIL,
    EVENT_RESULT,
)
from custom_components.myhyundai_aircon.coordinator import (
    MyHyundaiCoordinator,
)
from custom_components.myhyundai_aircon.executor import SequenceError

SUCCESS_RESULT = {
    "sequence": "aircon_on",
    "result": "success",
    "code": None,
    "elapsed_sec": 1.0,
    "notification_text": "공조가 켜졌습니다.",
}

# Guards off unless a test opts in.
QUIET_OPTIONS = {
    CONF_COMMAND_MIN_GAP_SEC: 0,
    CONF_COOLDOWN_SEC: 0,
    CONF_RETRY_GAP_SEC: 0,
}


def _make_coordinator(
    hass: HomeAssistant, options: dict
) -> tuple[MyHyundaiCoordinator, MagicMock]:
    """Build a coordinator around a mocked client and executor."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    client = MagicMock()
    client.async_shell = AsyncMock(return_value="")
    coordinator = MyHyundaiCoordinator(hass, entry, client)
    executor = MagicMock()
    executor.recipe.package = "com.hyundai.oneapp.kr"
    executor.last_notification_text = "공조가 켜졌습니다."
    executor.last_screen_checked = "840x2289"
    executor.async_run_sequence = AsyncMock(return_value=dict(SUCCESS_RESULT))
    coordinator.executor = executor
    return coordinator, executor


async def test_min_gap_guard(hass: HomeAssistant) -> None:
    """A second run inside the minimum gap is rejected (T7)."""
    coordinator, _ = _make_coordinator(
        hass,
        QUIET_OPTIONS | {CONF_COMMAND_MIN_GAP_SEC: 3},
    )
    await coordinator.async_execute("aircon_on")
    with pytest.raises(SequenceError) as err:
        await coordinator.async_execute("aircon_on")
    assert err.value.code == ERR_MIN_GAP


async def test_cooldown_guard_and_ignore_flag(
    hass: HomeAssistant,
) -> None:
    """Cooldown blocks after a success; ignore_guards bypasses."""
    coordinator, _ = _make_coordinator(
        hass, QUIET_OPTIONS | {CONF_COOLDOWN_SEC: 60}
    )
    await coordinator.async_execute("aircon_on")
    with pytest.raises(SequenceError) as err:
        await coordinator.async_execute("aircon_on")
    assert err.value.code == ERR_COOLDOWN
    result = await coordinator.async_execute("aircon_on", ignore_guards=True)
    assert result["result"] == "success"


async def test_battery_guard(hass: HomeAssistant) -> None:
    """A battery reading under the floor blocks the run (T2)."""
    coordinator, executor = _make_coordinator(
        hass,
        QUIET_OPTIONS
        | {
            CONF_BATTERY_SENSOR: "sensor.vehicle_battery",
            CONF_BATTERY_FLOOR_PCT: 40,
        },
    )
    hass.states.async_set("sensor.vehicle_battery", "20")
    with pytest.raises(SequenceError) as err:
        await coordinator.async_execute("aircon_on")
    assert err.value.code == ERR_BATTERY_LOW
    executor.async_run_sequence.assert_not_awaited()

    hass.states.async_set("sensor.vehicle_battery", "80")
    result = await coordinator.async_execute("aircon_on")
    assert result["result"] == "success"


async def test_vehicle_fail_retries(hass: HomeAssistant) -> None:
    """E_VEHICLE_FAIL retries after the gap and can succeed (T8-ish)."""
    coordinator, executor = _make_coordinator(hass, QUIET_OPTIONS)
    executor.async_run_sequence = AsyncMock(
        side_effect=[
            SequenceError(ERR_VEHICLE_FAIL, "doors open"),
            dict(SUCCESS_RESULT),
        ]
    )
    result = await coordinator.async_execute("aircon_on")
    assert result["attempt"] == 2
    assert coordinator.last_result == "success"


async def test_timeout_retry_force_stops_app(
    hass: HomeAssistant,
) -> None:
    """E_TIMEOUT force-stops the app before retrying (spec §9.3)."""
    coordinator, executor = _make_coordinator(hass, QUIET_OPTIONS)
    executor.async_run_sequence = AsyncMock(
        side_effect=[
            SequenceError(ERR_TIMEOUT, "no notification"),
            dict(SUCCESS_RESULT),
        ]
    )
    await coordinator.async_execute("aircon_on")
    coordinator.client.async_shell.assert_awaited_with(
        "am force-stop com.hyundai.oneapp.kr"
    )


async def test_non_retryable_fails_once_and_dumps(
    hass: HomeAssistant,
) -> None:
    """A non-retryable code fails immediately and saves a dump."""
    coordinator, executor = _make_coordinator(hass, QUIET_OPTIONS)
    coordinator.capture_dump = AsyncMock()
    executor.async_run_sequence = AsyncMock(
        side_effect=SequenceError(ERR_UNKNOWN_SCREEN, "no node")
    )
    events = []
    hass.bus.async_listen(EVENT_RESULT, lambda event: events.append(event))
    with pytest.raises(SequenceError):
        await coordinator.async_execute("aircon_on")
    await hass.async_block_till_done()
    assert executor.async_run_sequence.await_count == 1
    coordinator.capture_dump.assert_awaited_once()
    assert coordinator.last_result == "failure"
    assert coordinator.last_error == ERR_UNKNOWN_SCREEN
    assert events[0].data["code"] == ERR_UNKNOWN_SCREEN


async def test_success_event_payload(hass: HomeAssistant) -> None:
    """The §9.4 event carries the run details."""
    coordinator, _ = _make_coordinator(hass, QUIET_OPTIONS)
    events = []
    hass.bus.async_listen(EVENT_RESULT, lambda event: events.append(event))
    await coordinator.async_execute("aircon_on")
    await hass.async_block_till_done()
    data = events[0].data
    assert data["result"] == "success"
    assert data["attempt"] == 1
    assert data["screen_checked"] == "840x2289"
    assert data["notification_text"] == "공조가 켜졌습니다."
