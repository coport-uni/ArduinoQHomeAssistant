"""Config flow for the myhyundai_aircon integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

from .adb_client import (
    AdbClient,
    AuthRejectedError,
    CannotConnectError,
    InvalidDeviceError,
)
from .const import (
    CONF_ADBKEY_PATH,
    CONF_AIRCON_MAX_MINUTES,
    CONF_BASELINE_SCREEN,
    CONF_BATTERY_FLOOR_PCT,
    CONF_BATTERY_SENSOR,
    CONF_COMMAND_MIN_GAP_SEC,
    CONF_COOLDOWN_SEC,
    CONF_DEVICE_NAME,
    CONF_DUMP_ON_FAILURE,
    CONF_RECIPE_FILE,
    CONF_RETRY_GAP_SEC,
    CONF_RETRY_MAX,
    CONF_SCREEN_CHECK_ENABLED,
    CONF_SEQUENCE_TIMEOUT_SEC,
    CONF_VEHICLE_POLL_MINUTES,
    CONF_WIDGET_REFRESH_ENABLED,
    DEFAULT_ADBKEY_FILENAME,
    DEFAULT_AIRCON_MAX_MINUTES,
    DEFAULT_BATTERY_FLOOR_PCT,
    DEFAULT_COMMAND_MIN_GAP_SEC,
    DEFAULT_COOLDOWN_SEC,
    DEFAULT_DEVICE_NAME,
    DEFAULT_PORT,
    DEFAULT_RECIPE_FILE,
    DEFAULT_RETRY_GAP_SEC,
    DEFAULT_RETRY_MAX,
    DEFAULT_SEQUENCE_TIMEOUT_SEC,
    DEFAULT_VEHICLE_POLL_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_ADBKEY_PATH, default=""): str,
        vol.Optional(CONF_DEVICE_NAME, default=DEFAULT_DEVICE_NAME): str,
    }
)


class MyHyundaiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the Android device by proving the ADB connection works.

    The step connects, reads the device serial (used as the unique
    ID), and stores the effective screen resolution as the baseline
    that later screen checks compare against. The user never types
    the resolution, per spec §5.1.
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> MyHyundaiOptionsFlow:
        """Return the options flow handler."""
        return MyHyundaiOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial connection form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            adbkey_path = user_input[CONF_ADBKEY_PATH].strip() or (
                self.hass.config.path(".storage", DEFAULT_ADBKEY_FILENAME)
            )
            client = AdbClient(
                user_input[CONF_HOST], user_input[CONF_PORT], adbkey_path
            )
            try:
                await client.async_connect()
                serial = await client.async_get_serial()
                baseline_screen = await client.async_get_screen_size()
            except AuthRejectedError:
                errors["base"] = "auth_rejected"
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidDeviceError:
                errors["base"] = "invalid_device"
            finally:
                await client.async_close()
            if not errors:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                _LOGGER.info(
                    "Validated device %s, baseline screen %s",
                    serial,
                    baseline_screen,
                )
                return self.async_create_entry(
                    title=user_input[CONF_DEVICE_NAME],
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_ADBKEY_PATH: adbkey_path,
                        CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
                        CONF_BASELINE_SCREEN: baseline_screen,
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _USER_SCHEMA, user_input
            ),
            errors=errors,
        )


def _positive_int_selector(maximum: int) -> selector.NumberSelector:
    """A whole-number box selector from 0 to ``maximum``."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_RECIPE_FILE, default=DEFAULT_RECIPE_FILE): str,
        # No default: an empty EntitySelector value must simply be
        # absent, or its "" fails entity-id validation on submit.
        vol.Optional(CONF_BATTERY_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")
        ),
        vol.Optional(
            CONF_BATTERY_FLOOR_PCT,
            default=DEFAULT_BATTERY_FLOOR_PCT,
        ): vol.All(_positive_int_selector(100), vol.Coerce(int)),
        vol.Optional(
            CONF_COMMAND_MIN_GAP_SEC,
            default=DEFAULT_COMMAND_MIN_GAP_SEC,
        ): vol.All(_positive_int_selector(3600), vol.Coerce(int)),
        vol.Optional(CONF_COOLDOWN_SEC, default=DEFAULT_COOLDOWN_SEC): vol.All(
            _positive_int_selector(3600), vol.Coerce(int)
        ),
        vol.Optional(
            CONF_AIRCON_MAX_MINUTES,
            default=DEFAULT_AIRCON_MAX_MINUTES,
        ): vol.All(_positive_int_selector(60), vol.Coerce(int)),
        vol.Optional(
            CONF_SEQUENCE_TIMEOUT_SEC,
            default=DEFAULT_SEQUENCE_TIMEOUT_SEC,
        ): vol.All(_positive_int_selector(600), vol.Coerce(int)),
        vol.Optional(CONF_RETRY_MAX, default=DEFAULT_RETRY_MAX): vol.All(
            _positive_int_selector(5), vol.Coerce(int)
        ),
        vol.Optional(
            CONF_RETRY_GAP_SEC, default=DEFAULT_RETRY_GAP_SEC
        ): vol.All(_positive_int_selector(600), vol.Coerce(int)),
        vol.Optional(CONF_SCREEN_CHECK_ENABLED, default=True): bool,
        vol.Optional(CONF_DUMP_ON_FAILURE, default=True): bool,
        vol.Optional(
            CONF_VEHICLE_POLL_MINUTES,
            default=DEFAULT_VEHICLE_POLL_MINUTES,
        ): vol.All(_positive_int_selector(1440), vol.Coerce(int)),
        vol.Optional(CONF_WIDGET_REFRESH_ENABLED, default=False): bool,
    }
)


class MyHyundaiOptionsFlow(OptionsFlow):
    """Adjust the spec §5.2 tuning values."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
