"""Unit tests for the myhyundai_aircon ADB client wrapper."""

from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from adb_shell import exceptions as adb_exceptions

from custom_components.myhyundai_aircon.adb_client import (
    AdbClient,
    AuthRejectedError,
    CannotConnectError,
    InvalidDeviceError,
    parse_screen_size,
)

WM_SIZE_PHYSICAL_ONLY = "Physical size: 832x2268\n"
WM_SIZE_WITH_OVERRIDE = "Physical size: 832x2268\nOverride size: 840x2289\n"


def _make_client() -> AdbClient:
    """Build a client whose signer loading is stubbed out."""
    client = AdbClient("192.0.2.1", 5555, "/tmp/adbkey")
    client._signer = object()
    return client


def test_parse_screen_size_prefers_override() -> None:
    """The override resolution wins because screencaps use it."""
    assert parse_screen_size(WM_SIZE_WITH_OVERRIDE) == "840x2289"


def test_parse_screen_size_falls_back_to_physical() -> None:
    """Without an override line the physical size is used."""
    assert parse_screen_size(WM_SIZE_PHYSICAL_ONLY) == "832x2268"


def test_parse_screen_size_rejects_garbage() -> None:
    """Output without a resolution raises InvalidDeviceError."""
    with pytest.raises(InvalidDeviceError):
        parse_screen_size("sh: wm: inaccessible or not found\n")


async def test_connect_maps_auth_error() -> None:
    """A rejected RSA key surfaces as AuthRejectedError."""
    client = _make_client()
    with patch.object(
        client._device,
        "connect",
        AsyncMock(side_effect=adb_exceptions.DeviceAuthError("denied")),
    ):
        with pytest.raises(AuthRejectedError):
            await client.async_connect()


async def test_connect_maps_tcp_timeout() -> None:
    """A TCP-level failure surfaces as CannotConnectError."""
    client = _make_client()
    with patch.object(
        client._device,
        "connect",
        AsyncMock(side_effect=adb_exceptions.TcpTimeoutException("t")),
    ):
        with pytest.raises(CannotConnectError):
            await client.async_connect()


async def test_shell_requires_connection() -> None:
    """Running shell without a session raises CannotConnectError."""
    client = _make_client()
    with pytest.raises(CannotConnectError):
        await client.async_shell("echo ok")


async def test_shell_returns_output() -> None:
    """Shell output is passed through unchanged."""
    client = _make_client()
    with (
        patch.object(
            type(client._device),
            "available",
            PropertyMock(return_value=True),
        ),
        patch.object(client._device, "shell", AsyncMock(return_value="ok\n")),
    ):
        assert await client.async_shell("echo ok") == "ok\n"


async def test_shell_drop_closes_session() -> None:
    """A mid-command drop closes the session and maps the error."""
    client = _make_client()
    with (
        patch.object(
            type(client._device),
            "available",
            PropertyMock(return_value=True),
        ),
        patch.object(
            client._device,
            "shell",
            AsyncMock(side_effect=adb_exceptions.AdbConnectionError("gone")),
        ),
        patch.object(client._device, "close", AsyncMock()) as close,
    ):
        with pytest.raises(CannotConnectError):
            await client.async_shell("echo ok")
    close.assert_awaited_once()


async def test_get_serial_strips_and_validates() -> None:
    """The serial probe trims whitespace and rejects empties."""
    client = _make_client()
    with patch.object(
        client,
        "async_shell",
        AsyncMock(return_value="R3CR80H1GBN\n"),
    ):
        assert await client.async_get_serial() == "R3CR80H1GBN"
    with patch.object(client, "async_shell", AsyncMock(return_value="\n")):
        with pytest.raises(InvalidDeviceError):
            await client.async_get_serial()
