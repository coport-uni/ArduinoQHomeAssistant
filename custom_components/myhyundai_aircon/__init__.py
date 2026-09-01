"""The myhyundai_aircon integration.

Controls Hyundai remote climate by driving the MyHyundai home-screen
widget on a dedicated Android device over ADB TCP. This module wires
the config entry to the ADB client, the coordinator (which also owns
guards and retries), the recipe executor, and the entity platforms,
and registers the capture_dump / run_sequence / reload_recipe
services.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .adb_client import AdbClient, CannotConnectError
from .const import (
    ATTR_IGNORE_GUARDS,
    ATTR_LABEL,
    ATTR_SEQUENCE,
    CONF_ADBKEY_PATH,
    CONF_BASELINE_SCREEN,
    CONF_RECIPE_FILE,
    DEFAULT_RECIPE_FILE,
    DEVICE_SCREENSHOT_PATH,
    DOMAIN,
    DUMP_DIR_NAME,
    DUMP_RETENTION_FILES,
    SERVICE_CAPTURE_DUMP,
    SERVICE_RELOAD_RECIPE,
    SERVICE_RUN_SEQUENCE,
)
from .coordinator import MyHyundaiCoordinator
from .executor import SequenceError, SequenceExecutor
from .recipe import RecipeError, load_recipe

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

_RECIPES_DIR = Path(__file__).parent / "recipes"

_CAPTURE_DUMP_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_LABEL, default="manual"): cv.slugify}
)
_RUN_SEQUENCE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SEQUENCE): cv.string,
        vol.Optional(ATTR_IGNORE_GUARDS, default=False): cv.boolean,
    }
)


@dataclass
class MyHyundaiRuntime:
    """Per-entry objects shared by services and platforms."""

    coordinator: MyHyundaiCoordinator
    executor: SequenceExecutor
    recipe_path: Path


type MyHyundaiConfigEntry = ConfigEntry[MyHyundaiRuntime]


async def async_setup_entry(
    hass: HomeAssistant, entry: MyHyundaiConfigEntry
) -> bool:
    """Connect, load the recipe, and set up platforms and services.

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

    recipe_path = _RECIPES_DIR / entry.options.get(
        CONF_RECIPE_FILE, DEFAULT_RECIPE_FILE
    )
    try:
        recipe = await hass.async_add_executor_job(load_recipe, recipe_path)
    except RecipeError as err:
        await client.async_close()
        raise HomeAssistantError(str(err)) from err

    executor = SequenceExecutor(
        client, recipe, entry.data[CONF_BASELINE_SCREEN]
    )
    coordinator.executor = executor

    async def _capture_failure_dump(label: str) -> None:
        await _capture_dump_files(hass, executor, client, label)

    coordinator.capture_dump = _capture_failure_dump

    entry.runtime_data = MyHyundaiRuntime(coordinator, executor, recipe_path)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_handle_options_update))
    # The first refresh ran before the executor existed, so the
    # initial vehicle-data scrape was skipped; request another
    # (debounced) update now that everything is wired.
    entry.async_create_task(hass, coordinator.async_request_refresh())
    return True


async def _handle_options_update(
    hass: HomeAssistant, entry: MyHyundaiConfigEntry
) -> None:
    """Reload the entry so new options take effect everywhere."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: MyHyundaiConfigEntry
) -> bool:
    """Unload platforms and close the ADB session."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    await entry.runtime_data.coordinator.client.async_close()
    return unloaded


def _get_runtime(hass: HomeAssistant) -> MyHyundaiRuntime:
    """Return the runtime of the single loaded entry.

    Raises:
        HomeAssistantError: If no entry is currently loaded.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    raise HomeAssistantError(f"no loaded {DOMAIN} entry")


def _prune_dump_dir(dump_dir: Path) -> None:
    """Delete the oldest dump files beyond the retention cap.

    Runs in an executor job. Timestamped names sort chronologically,
    so plain name order is age order.
    """
    files = sorted(dump_dir.iterdir())
    for stale in files[: max(0, len(files) - DUMP_RETENTION_FILES)]:
        stale.unlink()
        _LOGGER.debug("Pruned old dump %s", stale.name)


async def _capture_dump_files(
    hass: HomeAssistant,
    executor: SequenceExecutor,
    client: AdbClient,
    label: str,
) -> Path:
    """Save the UI hierarchy XML and a screenshot PNG pair.

    Shared by the capture_dump service and the dump-on-failure hook.

    Returns:
        The path base (without extension) of the saved pair.

    Raises:
        HomeAssistantError: When the device cannot be captured.
    """
    stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
    dump_dir = Path(hass.config.path(DUMP_DIR_NAME))
    base = dump_dir / f"{stamp}-{label}"
    await hass.async_add_executor_job(os.makedirs, dump_dir, 0o755, True)
    try:
        xml_text = await executor.async_capture_ui_xml()
        await client.async_shell(f"screencap -p {DEVICE_SCREENSHOT_PATH}")
        await client.async_pull(DEVICE_SCREENSHOT_PATH, f"{base}.png")
        await client.async_shell(f"rm {DEVICE_SCREENSHOT_PATH}")
    except (SequenceError, CannotConnectError) as err:
        raise HomeAssistantError(f"capture_dump failed: {err}") from err
    await hass.async_add_executor_job(
        Path(f"{base}.xml").write_text, xml_text, "utf-8"
    )
    await hass.async_add_executor_job(_prune_dump_dir, dump_dir)
    _LOGGER.info("Dump saved: %s.{xml,png}", base)
    return base


def _register_services(hass: HomeAssistant) -> None:
    """Register domain services once, no matter how many entries."""
    if hass.services.has_service(DOMAIN, SERVICE_CAPTURE_DUMP):
        return

    async def handle_capture_dump(call: ServiceCall) -> None:
        """Save the UI hierarchy and a screenshot for analysis."""
        runtime = _get_runtime(hass)
        base = await _capture_dump_files(
            hass,
            runtime.executor,
            runtime.coordinator.client,
            call.data[ATTR_LABEL],
        )
        persistent_notification.async_create(
            hass,
            f"UI dump saved to {base}.xml and .png",
            title="MyHyundai dump captured",
        )

    async def handle_run_sequence(call: ServiceCall) -> None:
        """Run a recipe sequence through the guarded orchestrator."""
        runtime = _get_runtime(hass)
        try:
            await runtime.coordinator.async_execute(
                call.data[ATTR_SEQUENCE],
                ignore_guards=call.data[ATTR_IGNORE_GUARDS],
            )
        except SequenceError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_reload_recipe(call: ServiceCall) -> None:
        """Re-read the recipe file without restarting HA."""
        runtime = _get_runtime(hass)
        try:
            recipe = await hass.async_add_executor_job(
                load_recipe, runtime.recipe_path
            )
        except RecipeError as err:
            raise HomeAssistantError(str(err)) from err
        runtime.executor.recipe = recipe
        _LOGGER.info("Recipe reloaded from %s", runtime.recipe_path)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAPTURE_DUMP,
        handle_capture_dump,
        schema=_CAPTURE_DUMP_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_SEQUENCE,
        handle_run_sequence,
        schema=_RUN_SEQUENCE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RELOAD_RECIPE, handle_reload_recipe
    )
