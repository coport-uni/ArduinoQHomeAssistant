"""The myhyundai_aircon integration.

Controls Hyundai remote climate by driving the MyHyundai home-screen
widget on a dedicated Android device over ADB TCP. This module wires
the config entry to the ADB client, the connectivity coordinator,
and the recipe executor, and registers the capture_dump /
run_sequence / reload_recipe services. Entity platforms arrive in a
later implementation stage.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .adb_client import AdbClient, CannotConnectError
from .const import (
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
    EVENT_RESULT,
    SERVICE_CAPTURE_DUMP,
    SERVICE_RELOAD_RECIPE,
    SERVICE_RUN_SEQUENCE,
)
from .coordinator import MyHyundaiCoordinator
from .executor import SequenceError, SequenceExecutor
from .recipe import RecipeError, load_recipe

_LOGGER = logging.getLogger(__name__)

_RECIPES_DIR = Path(__file__).parent / "recipes"

_CAPTURE_DUMP_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_LABEL, default="manual"): cv.slugify}
)
_RUN_SEQUENCE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SEQUENCE): cv.string,
        # ignore_guards is accepted for spec §7.2 compatibility but
        # has no effect until the guards stage lands.
        vol.Optional("ignore_guards", default=False): cv.boolean,
    }
)


@dataclass
class MyHyundaiRuntime:
    """Per-entry objects shared by services and future platforms."""

    coordinator: MyHyundaiCoordinator
    executor: SequenceExecutor
    recipe_path: Path


type MyHyundaiConfigEntry = ConfigEntry[MyHyundaiRuntime]


async def async_setup_entry(
    hass: HomeAssistant, entry: MyHyundaiConfigEntry
) -> bool:
    """Connect, load the recipe, and register the services.

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
    entry.runtime_data = MyHyundaiRuntime(coordinator, executor, recipe_path)
    _register_services(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MyHyundaiConfigEntry
) -> bool:
    """Close the ADB session when the entry is unloaded."""
    await entry.runtime_data.coordinator.client.async_close()
    return True


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


def _register_services(hass: HomeAssistant) -> None:
    """Register domain services once, no matter how many entries."""
    if hass.services.has_service(DOMAIN, SERVICE_CAPTURE_DUMP):
        return

    async def handle_capture_dump(call: ServiceCall) -> None:
        """Save the UI hierarchy and a screenshot for analysis."""
        runtime = _get_runtime(hass)
        executor = runtime.executor
        client = runtime.coordinator.client
        stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
        base = f"{stamp}-{call.data[ATTR_LABEL]}"
        dump_dir = Path(hass.config.path(DUMP_DIR_NAME))
        await hass.async_add_executor_job(os.makedirs, dump_dir, 0o755, True)
        try:
            xml_text = await executor.async_capture_ui_xml()
            await client.async_shell(f"screencap -p {DEVICE_SCREENSHOT_PATH}")
            await client.async_pull(
                DEVICE_SCREENSHOT_PATH, str(dump_dir / f"{base}.png")
            )
            await client.async_shell(f"rm {DEVICE_SCREENSHOT_PATH}")
        except (SequenceError, CannotConnectError) as err:
            raise HomeAssistantError(f"capture_dump failed: {err}") from err
        await hass.async_add_executor_job(
            (dump_dir / f"{base}.xml").write_text, xml_text, "utf-8"
        )
        await hass.async_add_executor_job(_prune_dump_dir, dump_dir)
        _LOGGER.info("Dump saved: %s.{xml,png}", dump_dir / base)
        persistent_notification.async_create(
            hass,
            f"UI dump saved to {dump_dir / base}.xml and .png",
            title="MyHyundai dump captured",
        )

    async def handle_run_sequence(call: ServiceCall) -> None:
        """Run a recipe sequence and publish the §9.4 result event."""
        runtime = _get_runtime(hass)
        name = call.data[ATTR_SEQUENCE]
        try:
            result = await runtime.executor.async_run_sequence(name)
        except SequenceError as err:
            hass.bus.async_fire(
                EVENT_RESULT,
                {
                    "sequence": name,
                    "result": "failure",
                    "code": err.code,
                },
            )
            raise HomeAssistantError(str(err)) from err
        hass.bus.async_fire(EVENT_RESULT, result)

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
