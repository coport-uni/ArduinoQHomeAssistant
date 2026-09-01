"""Config flow for the myhyundai_aircon integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .adb_client import (
    AdbClient,
    AuthRejectedError,
    CannotConnectError,
    InvalidDeviceError,
)
from .const import (
    CONF_ADBKEY_PATH,
    CONF_BASELINE_SCREEN,
    CONF_DEVICE_NAME,
    DEFAULT_ADBKEY_FILENAME,
    DEFAULT_DEVICE_NAME,
    DEFAULT_PORT,
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
