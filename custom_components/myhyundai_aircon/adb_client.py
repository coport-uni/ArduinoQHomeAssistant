"""ADB connection handling for the myhyundai_aircon integration.

Wraps ``adb_shell``'s asynchronous TCP device with the small surface
the integration needs: connect with an RSA key that is generated on
first use, run shell commands serialized behind a lock, and map the
library's failure modes onto three integration-level errors that the
config flow can present to the user.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from adb_shell import exceptions as adb_exceptions
from adb_shell.adb_device_async import AdbDeviceTcpAsync
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner

from .const import AUTH_TIMEOUT_S, CONNECT_TIMEOUT_S, SHELL_TIMEOUT_S

_LOGGER = logging.getLogger(__name__)

_SCREEN_SIZE_PATTERN = re.compile(r"^\d+x\d+$")


class AdbClientError(Exception):
    """Base error for ADB client failures."""


class CannotConnectError(AdbClientError):
    """The device is unreachable over TCP."""


class AuthRejectedError(AdbClientError):
    """The device rejected or timed out the RSA authorization."""


class InvalidDeviceError(AdbClientError):
    """The shell responded, but not like an Android device."""


def parse_screen_size(wm_size_output: str) -> str:
    """Extract the effective resolution from ``wm size`` output.

    Android reports a ``Physical size`` line and, when the display is
    scaled, an ``Override size`` line. Screenshots and UI dump bounds
    use the override, so it wins when present.

    Args:
        wm_size_output: Raw stdout of the ``wm size`` shell command.

    Returns:
        The resolution as ``"<width>x<height>"``.

    Raises:
        InvalidDeviceError: If no resolution line is found.
    """
    physical = None
    override = None
    for line in wm_size_output.splitlines():
        label, separator, value = line.partition(":")
        if not separator:
            continue
        value = value.strip()
        if not _SCREEN_SIZE_PATTERN.match(value):
            continue
        if "Override" in label:
            override = value
        elif "Physical" in label:
            physical = value
    size = override or physical
    if size is None:
        raise InvalidDeviceError(
            f"no resolution in wm size output: {wm_size_output!r}"
        )
    return size


class AdbClient:
    """Asynchronous ADB TCP client bound to one Android device."""

    def __init__(self, host: str, port: int, adbkey_path: str) -> None:
        """Store the target address and key path without connecting.

        Args:
            host: IP address of the Android device.
            port: ADB TCP port, normally 5555.
            adbkey_path: Private key file; created if missing.
        """
        self._adbkey_path = adbkey_path
        self._signer: PythonRSASigner | None = None
        self._lock = asyncio.Lock()
        self._device = AdbDeviceTcpAsync(
            host, port, default_transport_timeout_s=CONNECT_TIMEOUT_S
        )

    @property
    def is_connected(self) -> bool:
        """Return whether the ADB session is currently usable."""
        return self._device.available

    async def async_connect(self) -> None:
        """Open the ADB session, generating the RSA key on first use.

        Raises:
            CannotConnectError: If the TCP connection fails.
            AuthRejectedError: If the device rejects the RSA key or
                the user does not accept the authorization prompt.
        """
        if self._signer is None:
            loop = asyncio.get_running_loop()
            self._signer = await loop.run_in_executor(None, self._load_signer)
        try:
            await self._device.connect(
                rsa_keys=[self._signer], auth_timeout_s=AUTH_TIMEOUT_S
            )
        except adb_exceptions.DeviceAuthError as err:
            raise AuthRejectedError(str(err)) from err
        except (
            adb_exceptions.TcpTimeoutException,
            adb_exceptions.AdbConnectionError,
            adb_exceptions.AdbTimeoutError,
            ConnectionError,
            OSError,
            asyncio.TimeoutError,
        ) as err:
            raise CannotConnectError(str(err)) from err

    async def async_close(self) -> None:
        """Close the ADB session; safe to call when not connected."""
        try:
            await self._device.close()
        except OSError:
            _LOGGER.debug("Ignoring error while closing ADB session")

    async def async_shell(self, command: str) -> str:
        """Run a shell command on the device and return its output.

        Args:
            command: The shell command line to execute.

        Returns:
            Decoded stdout of the command, possibly empty.

        Raises:
            CannotConnectError: If there is no usable session or the
                session drops mid-command. The session is closed so
                the next connect starts clean.
        """
        if not self._device.available:
            raise CannotConnectError("ADB session is not connected")
        async with self._lock:
            _LOGGER.debug("ADB shell: %s", command)
            try:
                output = await self._device.shell(
                    command,
                    read_timeout_s=SHELL_TIMEOUT_S,
                    timeout_s=SHELL_TIMEOUT_S,
                )
            except (
                adb_exceptions.AdbConnectionError,
                adb_exceptions.AdbTimeoutError,
                adb_exceptions.TcpTimeoutException,
                ConnectionError,
                OSError,
                asyncio.TimeoutError,
            ) as err:
                await self.async_close()
                raise CannotConnectError(str(err)) from err
        return output or ""

    async def async_get_serial(self) -> str:
        """Return the device serial for use as a unique ID.

        Raises:
            InvalidDeviceError: If the device reports no serial.
        """
        serial = (await self.async_shell("getprop ro.serialno")).strip()
        if not serial:
            raise InvalidDeviceError("device reported an empty serial")
        return serial

    async def async_get_screen_size(self) -> str:
        """Return the effective screen resolution via ``wm size``."""
        return parse_screen_size(await self.async_shell("wm size"))

    def _load_signer(self) -> PythonRSASigner:
        """Load the RSA signer, generating a key pair if needed.

        Runs in an executor because it does blocking file I/O.
        """
        directory = os.path.dirname(self._adbkey_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not os.path.isfile(self._adbkey_path):
            _LOGGER.info("Generating new adbkey at %s", self._adbkey_path)
            keygen(self._adbkey_path)
        return PythonRSASigner.FromRSAKeyPath(self._adbkey_path)
