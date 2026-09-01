"""Connectivity coordinator and run orchestration for myhyundai_aircon.

Besides polling ADB reachability, the coordinator owns everything
around a sequence run: the spec §9 safety guards (minimum gap,
cooldown, battery floor), the retry ladder for E_TIMEOUT and
E_VEHICLE_FAIL, the failure dump hook, the last-run state the
entities display, and the §9.4 result event.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .adb_client import AdbClient, AdbClientError
from .const import (
    CONF_BATTERY_FLOOR_PCT,
    CONF_BATTERY_SENSOR,
    CONF_COMMAND_MIN_GAP_SEC,
    CONF_COOLDOWN_SEC,
    CONF_DUMP_ON_FAILURE,
    CONF_RETRY_GAP_SEC,
    CONF_RETRY_MAX,
    CONF_SCREEN_CHECK_ENABLED,
    CONF_SEQUENCE_TIMEOUT_SEC,
    COORDINATOR_INTERVAL_S,
    DEFAULT_BATTERY_FLOOR_PCT,
    DEFAULT_COMMAND_MIN_GAP_SEC,
    DEFAULT_COOLDOWN_SEC,
    DEFAULT_RETRY_GAP_SEC,
    DEFAULT_RETRY_MAX,
    DEFAULT_SEQUENCE_TIMEOUT_SEC,
    DOMAIN,
    ERR_BATTERY_LOW,
    ERR_COOLDOWN,
    ERR_MIN_GAP,
    ERR_TIMEOUT,
    ERR_VEHICLE_FAIL,
    EVENT_RESULT,
    RECONNECT_BACKOFF_S,
)
from .executor import SequenceError, SequenceExecutor

_LOGGER = logging.getLogger(__name__)

# Codes worth another attempt per the spec §9.3 table.
_RETRYABLE_CODES = (ERR_TIMEOUT, ERR_VEHICLE_FAIL)


class MyHyundaiCoordinator(DataUpdateCoordinator[bool]):
    """Polls ADB reachability and orchestrates sequence runs."""

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
        # Set by async_setup_entry once the recipe is loaded.
        self.executor: SequenceExecutor | None = None
        # Called with a label to save a dump after a failed run.
        self.capture_dump: Callable[[str], Awaitable[None]] | None = None
        self.last_result = "unknown"
        self.last_error = "none"
        self.last_notification = ""
        self.last_success_at: datetime | None = None
        self._last_attempt_monotonic: float | None = None
        self._last_success_monotonic: float | None = None

    async def async_execute(
        self, sequence: str, *, ignore_guards: bool = False
    ) -> dict:
        """Run a sequence with guards and retries, updating state.

        Args:
            sequence: Recipe sequence key to run.
            ignore_guards: Skip the §9 guard checks (service flag).

        Returns:
            The executor's result payload of the winning attempt.

        Raises:
            SequenceError: With the final error code after guards
                fail or every attempt is exhausted.
        """
        if not ignore_guards:
            self._check_guards()
        self._last_attempt_monotonic = time.monotonic()
        assert self.executor is not None
        self.executor.screen_check_enabled = self._option(
            CONF_SCREEN_CHECK_ENABLED, True
        )
        retry_max = self._option(CONF_RETRY_MAX, DEFAULT_RETRY_MAX)
        attempt = 0
        while True:
            attempt += 1
            try:
                async with asyncio.timeout(
                    self._option(
                        CONF_SEQUENCE_TIMEOUT_SEC,
                        DEFAULT_SEQUENCE_TIMEOUT_SEC,
                    )
                ):
                    result = await self.executor.async_run_sequence(sequence)
            except TimeoutError:
                error = SequenceError(ERR_TIMEOUT, "sequence timeout exceeded")
            except SequenceError as err:
                error = err
            else:
                result["attempt"] = attempt
                self._record_result(sequence, result, None)
                return result
            _LOGGER.warning(
                "Sequence %s attempt %d failed: %s",
                sequence,
                attempt,
                error,
            )
            await self._save_failure_dump(sequence, attempt)
            if error.code not in _RETRYABLE_CODES or attempt > retry_max:
                self._record_result(sequence, None, error)
                raise error
            await self._prepare_retry(error.code)

    def _check_guards(self) -> None:
        """Enforce minimum gap, cooldown, and battery floor.

        Raises:
            SequenceError: E_MIN_GAP, E_COOLDOWN, or E_BATTERY_LOW.
        """
        now = time.monotonic()
        min_gap = self._option(
            CONF_COMMAND_MIN_GAP_SEC, DEFAULT_COMMAND_MIN_GAP_SEC
        )
        if (
            self._last_attempt_monotonic is not None
            and now - self._last_attempt_monotonic < min_gap
        ):
            raise SequenceError(
                ERR_MIN_GAP,
                f"last command was under {min_gap} s ago",
            )
        cooldown = self._option(CONF_COOLDOWN_SEC, DEFAULT_COOLDOWN_SEC)
        if (
            self._last_success_monotonic is not None
            and now - self._last_success_monotonic < cooldown
        ):
            raise SequenceError(
                ERR_COOLDOWN,
                f"cooldown of {cooldown} s still active",
            )
        self._check_battery_guard()

    def _check_battery_guard(self) -> None:
        """Block the run when the phone battery is below the floor."""
        sensor = self._option(CONF_BATTERY_SENSOR, "")
        if not sensor:
            return
        floor = self._option(CONF_BATTERY_FLOOR_PCT, DEFAULT_BATTERY_FLOOR_PCT)
        state = self.hass.states.get(sensor)
        try:
            level = float(state.state) if state else None
        except ValueError:
            level = None
        if level is None:
            _LOGGER.warning(
                "Battery sensor %s unreadable; guard skipped", sensor
            )
            return
        if level < floor:
            raise SequenceError(
                ERR_BATTERY_LOW,
                f"battery {level:.0f}%% is under the {floor}%% floor",
            )

    async def _save_failure_dump(self, sequence: str, attempt: int) -> None:
        """Save a dump after a failed attempt when configured."""
        if not self._option(CONF_DUMP_ON_FAILURE, True):
            return
        if self.capture_dump is None:
            return
        try:
            await self.capture_dump(f"fail-{sequence}-{attempt}")
        except Exception:  # noqa: BLE001 - diagnostics must not mask
            _LOGGER.exception("Failure dump could not be saved")

    async def _prepare_retry(self, code: str) -> None:
        """Apply the per-code recovery before the next attempt."""
        if code == ERR_TIMEOUT and self.executor is not None:
            # Spec §9.3: force-stop the app before retrying so a
            # wedged foreground activity cannot block the widget.
            try:
                await self.client.async_shell(
                    f"am force-stop {self.executor.recipe.package}"
                )
            except AdbClientError:
                _LOGGER.warning("force-stop before retry failed")
        if code == ERR_VEHICLE_FAIL:
            await asyncio.sleep(
                self._option(CONF_RETRY_GAP_SEC, DEFAULT_RETRY_GAP_SEC)
            )

    def _record_result(
        self,
        sequence: str,
        result: dict | None,
        error: SequenceError | None,
    ) -> None:
        """Store the outcome, notify entities, and fire the event."""
        assert self.executor is not None
        if error is None and result is not None:
            self.last_result = "success"
            self.last_error = "none"
            self.last_success_at = dt_util.now()
            self._last_success_monotonic = time.monotonic()
        else:
            self.last_result = "failure"
            self.last_error = error.code if error else "unknown"
        self.last_notification = self.executor.last_notification_text
        self.async_update_listeners()
        self.hass.bus.async_fire(
            EVENT_RESULT,
            {
                "sequence": sequence,
                "result": self.last_result,
                "code": None if error is None else error.code,
                "elapsed_sec": (result.get("elapsed_sec") if result else None),
                "attempt": (result.get("attempt") if result else None),
                "screen_checked": self.executor.last_screen_checked,
                "notification_text": self.last_notification,
            },
        )

    def _option(self, key: str, default):
        """Read one options-flow value with its default."""
        return self.config_entry.options.get(key, default)

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
