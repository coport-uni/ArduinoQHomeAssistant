"""Unit tests for the myhyundai_aircon config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.myhyundai_aircon.adb_client import (
    AuthRejectedError,
    CannotConnectError,
)
from custom_components.myhyundai_aircon.const import (
    CONF_ADBKEY_PATH,
    CONF_BASELINE_SCREEN,
    DOMAIN,
)

USER_INPUT = {
    "host": "192.0.2.1",
    "port": 5555,
    "adbkey_path": "",
    "device_name": "myhyundai",
}


def _make_client_mock() -> MagicMock:
    """Mock an AdbClient that validates successfully."""
    client = MagicMock()
    client.async_connect = AsyncMock()
    client.async_get_serial = AsyncMock(return_value="R3CR80H1GBN")
    client.async_get_screen_size = AsyncMock(return_value="840x2289")
    client.async_close = AsyncMock()
    return client


async def _start_flow(hass: HomeAssistant):
    """Open the user step of the config flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """A working device yields an entry with the probed baseline."""
    result = await _start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with patch(
        "custom_components.myhyundai_aircon.config_flow.AdbClient",
        return_value=_make_client_mock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "myhyundai"
    assert result["data"][CONF_BASELINE_SCREEN] == "840x2289"
    # An empty key path is replaced by the .storage default.
    assert result["data"][CONF_ADBKEY_PATH].endswith("myhyundai_aircon_adbkey")
    assert result["result"].unique_id == "R3CR80H1GBN"


async def test_user_flow_shows_errors(hass: HomeAssistant) -> None:
    """Connection failures map to the spec §5.1 error keys."""
    for error, key in (
        (CannotConnectError("t"), "cannot_connect"),
        (AuthRejectedError("d"), "auth_rejected"),
    ):
        client = _make_client_mock()
        client.async_connect = AsyncMock(side_effect=error)
        result = await _start_flow(hass)
        with patch(
            "custom_components.myhyundai_aircon.config_flow.AdbClient",
            return_value=client,
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], USER_INPUT
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": key}
        client.async_close.assert_awaited_once()


async def test_user_flow_aborts_on_duplicate(hass: HomeAssistant) -> None:
    """The same device serial cannot be configured twice."""
    with patch(
        "custom_components.myhyundai_aircon.config_flow.AdbClient",
        return_value=_make_client_mock(),
    ):
        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
