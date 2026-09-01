"""Sequence executor for the myhyundai_aircon integration.

Runs the validated recipe steps against the Android device: UI-dump
parsing, node matching per spec §8.4, coordinate math on node
bounds, and one method per §8.3 action. Failures raise
SequenceError with a spec §9.3 error code so the service layer can
report them uniformly.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from .adb_client import AdbClient, AdbClientError
from .const import (
    DEVICE_UI_XML_PATH,
    ERR_COOLDOWN,
    ERR_DEVICE_OFFLINE,
    ERR_NOT_IMPLEMENTED,
    ERR_RECIPE_INCOMPLETE,
    ERR_SCREEN_MISMATCH,
    ERR_SESSION_EXPIRED,
    ERR_UNKNOWN_SCREEN,
    ERR_UNKNOWN_SEQUENCE,
    UI_POLL_INTERVAL_S,
)
from .recipe import Recipe, Step

_LOGGER = logging.getLogger(__name__)

_BOUNDS_PATTERN = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_LAUNCHER_FOCUS_PATTERN = re.compile(r"launcher|home", re.IGNORECASE)

# How the §8.4 match keys map onto UiNode attributes, split into
# exact-match keys and substring keys.
_EXACT_MATCH_ATTRS = {
    "resource_id": "resource_id",
    "text": "text",
    "content_desc": "content_desc",
    "class": "class_name",
    "package": "package",
}
_CONTAINS_MATCH_ATTRS = {"text_contains": "text"}

_WAKE_SETTLE_S = 1.0
_HOME_FOCUS_TIMEOUT_S = 5.0


class SequenceError(Exception):
    """A step failed with a spec §9.3 error code."""

    def __init__(self, code: str, message: str) -> None:
        """Attach the error code to the message."""
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class UiNode:
    """One node from a uiautomator UI dump."""

    resource_id: str
    text: str
    content_desc: str
    class_name: str
    package: str
    bounds: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        """Return the tap point at the middle of the bounds."""
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2


def parse_bounds(bounds_text: str) -> tuple[int, int, int, int]:
    """Parse a uiautomator ``[x1,y1][x2,y2]`` bounds string.

    Raises:
        SequenceError: With E_UNKNOWN_SCREEN if the format is off.
    """
    found = _BOUNDS_PATTERN.match(bounds_text or "")
    if not found:
        raise SequenceError(
            ERR_UNKNOWN_SCREEN, f"unparseable bounds {bounds_text!r}"
        )
    return tuple(int(part) for part in found.groups())


def parse_ui_dump(xml_text: str) -> list[UiNode]:
    """Turn a uiautomator XML dump into a flat node list.

    Nodes without parseable bounds are skipped; they cannot be
    tapped anyway.

    Raises:
        SequenceError: With E_UNKNOWN_SCREEN if the XML is broken.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as err:
        raise SequenceError(
            ERR_UNKNOWN_SCREEN, f"unparseable UI dump: {err}"
        ) from err
    nodes = []
    for element in root.iter("node"):
        try:
            bounds = parse_bounds(element.get("bounds", ""))
        except SequenceError:
            continue
        nodes.append(
            UiNode(
                resource_id=element.get("resource-id", ""),
                text=element.get("text", ""),
                content_desc=element.get("content-desc", ""),
                class_name=element.get("class", ""),
                package=element.get("package", ""),
                bounds=bounds,
            )
        )
    return nodes


def match_nodes(nodes: list[UiNode], match: dict[str, Any]) -> list[UiNode]:
    """Return the nodes satisfying every condition in ``match``."""
    results = []
    for node in nodes:
        for key, attr in _EXACT_MATCH_ATTRS.items():
            if key in match and getattr(node, attr) != match[key]:
                break
        else:
            for key, attr in _CONTAINS_MATCH_ATTRS.items():
                if key in match and match[key] not in getattr(node, attr):
                    break
            else:
                results.append(node)
    return results


def select_node(nodes: list[UiNode], match: dict[str, Any]) -> UiNode:
    """Pick the target node per the spec §8.4 selection rules.

    Raises:
        SequenceError: With E_UNKNOWN_SCREEN when nothing matches or
            an explicit index is out of range.
    """
    candidates = match_nodes(nodes, match)
    if not candidates:
        raise SequenceError(ERR_UNKNOWN_SCREEN, f"no node matches {match!r}")
    index = match.get("index")
    if index is None:
        if len(candidates) > 1:
            _LOGGER.warning(
                "%d nodes match %r without an index; using the first",
                len(candidates),
                match,
            )
        return candidates[0]
    if index >= len(candidates):
        raise SequenceError(
            ERR_UNKNOWN_SCREEN,
            f"index {index} out of range for {match!r}"
            f" ({len(candidates)} matches)",
        )
    return candidates[index]


class SequenceExecutor:
    """Runs recipe sequences on the device, one at a time."""

    def __init__(
        self,
        client: AdbClient,
        recipe: Recipe,
        baseline_screen: str,
    ) -> None:
        """Bind the executor to a client, recipe, and baseline.

        Args:
            client: The connected ADB client.
            recipe: The validated recipe to execute from.
            baseline_screen: Resolution stored at config time; used
                when the recipe says ``"AUTO"``.
        """
        self._client = client
        self.recipe = recipe
        self._baseline_screen = baseline_screen
        self._lock = asyncio.Lock()

    async def async_run_sequence(self, name: str) -> dict[str, Any]:
        """Run one named sequence to completion.

        Args:
            name: Sequence key inside the recipe.

        Returns:
            A result payload for the §9.4 event: sequence, result,
            code, and elapsed_sec.

        Raises:
            SequenceError: E_COOLDOWN if a run is already active,
                E_UNKNOWN_SEQUENCE / E_RECIPE_INCOMPLETE for recipe
                problems, or whatever code the failing step raised.
        """
        if self._lock.locked():
            raise SequenceError(
                ERR_COOLDOWN, "another sequence is already running"
            )
        sequence = self.recipe.sequences.get(name)
        if sequence is None:
            raise SequenceError(
                ERR_UNKNOWN_SEQUENCE, f"no sequence named {name!r}"
            )
        if sequence.has_placeholders or not sequence.steps:
            raise SequenceError(
                ERR_RECIPE_INCOMPLETE,
                f"sequence {name!r} still contains placeholders or"
                " has no steps; fill it from a capture_dump",
            )
        async with self._lock:
            started = time.monotonic()
            _LOGGER.info("Sequence %s started", name)
            for index, step in enumerate(sequence.steps):
                await self._run_step(name, index, step)
            elapsed = round(time.monotonic() - started, 1)
            _LOGGER.info("Sequence %s succeeded in %.1f s", name, elapsed)
            return {
                "sequence": name,
                "result": "success",
                "code": None,
                "elapsed_sec": elapsed,
            }

    async def async_capture_ui_xml(self) -> str:
        """Dump the current UI hierarchy and return the XML text."""
        output = await self._shell(
            f"uiautomator dump {DEVICE_UI_XML_PATH} >/dev/null 2>&1;"
            f" cat {DEVICE_UI_XML_PATH}"
        )
        if "<hierarchy" not in output:
            raise SequenceError(
                ERR_UNKNOWN_SCREEN,
                f"uiautomator dump produced no hierarchy: {output[:120]!r}",
            )
        return output

    async def _run_step(self, name: str, index: int, step: Step) -> None:
        """Dispatch one step, honoring the ``optional`` flag."""
        _LOGGER.debug(
            "Sequence %s step %d: %s %s",
            name,
            index,
            step.action,
            step.params,
        )
        handler = getattr(self, f"_step_{step.action}")
        try:
            await handler(**step.params)
        except SequenceError as err:
            if not step.optional:
                raise
            _LOGGER.warning(
                "Optional step %d (%s) of %s failed: %s",
                index,
                step.action,
                name,
                err,
            )

    async def _shell(self, command: str) -> str:
        """Run a shell command, mapping client errors to a code."""
        try:
            return await self._client.async_shell(command)
        except AdbClientError as err:
            raise SequenceError(ERR_DEVICE_OFFLINE, str(err)) from err

    async def _get_nodes(self) -> list[UiNode]:
        """Capture and parse the UI, checking for the login screen."""
        nodes = parse_ui_dump(await self.async_capture_ui_xml())
        markers = self.recipe.login_markers
        if markers:
            texts = [node.text for node in nodes if node.text]
            for marker in markers:
                if any(marker in text for text in texts):
                    raise SequenceError(
                        ERR_SESSION_EXPIRED,
                        f"login marker {marker!r} on screen;"
                        " re-login on the device",
                    )
        return nodes

    async def _get_focus(self) -> str:
        """Return the current window focus lines from dumpsys."""
        return await self._shell(
            "dumpsys window windows 2>/dev/null"
            " | grep -E 'mCurrentFocus|mFocusedApp'"
            " || dumpsys window"
            " | grep -E 'mCurrentFocus|mFocusedApp'"
        )

    async def _step_keyevent(self, key: str) -> None:
        await self._shell(f"input keyevent {key}")

    async def _step_wake(self) -> None:
        """Wake the display if dumpsys reports it asleep."""
        state = await self._shell("dumpsys power | grep mWakefulness=")
        if "Awake" in state:
            return
        await self._shell("input keyevent KEYCODE_WAKEUP")
        await asyncio.sleep(_WAKE_SETTLE_S)
        state = await self._shell("dumpsys power | grep mWakefulness=")
        if "Awake" not in state:
            raise SequenceError(
                ERR_UNKNOWN_SCREEN,
                f"display did not wake: {state.strip()!r}",
            )

    async def _step_home(self) -> None:
        """Press HOME and wait until a launcher window has focus."""
        await self._shell("input keyevent KEYCODE_HOME")
        deadline = time.monotonic() + _HOME_FOCUS_TIMEOUT_S
        while time.monotonic() < deadline:
            if _LAUNCHER_FOCUS_PATTERN.search(await self._get_focus()):
                return
            await asyncio.sleep(UI_POLL_INTERVAL_S)
        _LOGGER.warning("Launcher focus not confirmed after HOME")

    async def _step_launch_app(self, package: str) -> None:
        await self._shell(
            f"monkey -p {package}"
            " -c android.intent.category.LAUNCHER 1"
            " >/dev/null 2>&1"
        )

    async def _step_stop_app(self, package: str) -> None:
        await self._shell(f"am force-stop {package}")

    async def _step_wait_focus(self, pattern: str, timeout: float) -> None:
        """Wait until the focused window matches the regex pattern."""
        compiled = re.compile(pattern)
        deadline = time.monotonic() + timeout
        while True:
            focus = await self._get_focus()
            if compiled.search(focus):
                return
            if time.monotonic() >= deadline:
                raise SequenceError(
                    ERR_UNKNOWN_SCREEN,
                    f"focus never matched {pattern!r};"
                    f" last: {focus.strip()[:120]!r}",
                )
            await asyncio.sleep(UI_POLL_INTERVAL_S)

    async def _wait_for_node(
        self, match: dict[str, Any], timeout: float
    ) -> UiNode:
        """Poll UI dumps until a node matches, or time out."""
        deadline = time.monotonic() + timeout
        while True:
            nodes = await self._get_nodes()
            try:
                return select_node(nodes, match)
            except SequenceError:
                if time.monotonic() >= deadline:
                    raise
            await asyncio.sleep(UI_POLL_INTERVAL_S)

    async def _step_wait_node(
        self, match: dict[str, Any], timeout: float
    ) -> None:
        await self._wait_for_node(match, timeout)

    async def _step_tap_node(
        self, match: dict[str, Any], timeout: float
    ) -> None:
        """Find the node, then tap the center of its bounds."""
        node = await self._wait_for_node(match, timeout)
        x, y = node.center
        _LOGGER.debug("Tapping %r at (%d, %d)", match, x, y)
        await self._shell(f"input tap {x} {y}")

    async def _step_tap_ratio(self, x: float, y: float) -> None:
        """Tap at screen-relative coordinates; last-resort action."""
        width, height = await self._get_screen_dimensions()
        await self._shell(f"input tap {int(x * width)} {int(y * height)}")

    async def _step_swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration: int
    ) -> None:
        await self._shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")

    async def _step_sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def _step_assert_screen(self) -> None:
        """Compare the live resolution against the baseline."""
        expected = self.recipe.baseline_screen
        if expected == "AUTO":
            expected = self._baseline_screen
        try:
            current = await self._client.async_get_screen_size()
        except AdbClientError as err:
            raise SequenceError(ERR_DEVICE_OFFLINE, str(err)) from err
        if current != expected:
            raise SequenceError(
                ERR_SCREEN_MISMATCH,
                f"screen is {current}, expected {expected};"
                " check the fold state",
            )

    async def _step_await_notification(
        self,
        success_contains: list[str],
        failure_contains: list[str],
        timeout: float,
    ) -> None:
        """Placeholder until the notification stage (spec §11-6)."""
        raise SequenceError(
            ERR_NOT_IMPLEMENTED,
            "await_notification is not implemented yet;"
            " it arrives with notification.py",
        )

    async def _get_screen_dimensions(self) -> tuple[int, int]:
        """Return the live (width, height) for ratio taps."""
        try:
            size = await self._client.async_get_screen_size()
        except AdbClientError as err:
            raise SequenceError(ERR_DEVICE_OFFLINE, str(err)) from err
        width, _, height = size.partition("x")
        return int(width), int(height)
