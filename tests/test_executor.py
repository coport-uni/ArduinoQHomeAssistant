"""Unit tests for the myhyundai_aircon sequence executor."""

import asyncio

import pytest

from custom_components.myhyundai_aircon.const import (
    ERR_COOLDOWN,
    ERR_NOT_IMPLEMENTED,
    ERR_RECIPE_INCOMPLETE,
    ERR_SCREEN_MISMATCH,
    ERR_SESSION_EXPIRED,
    ERR_UNKNOWN_SCREEN,
    ERR_UNKNOWN_SEQUENCE,
)
from custom_components.myhyundai_aircon.executor import (
    SequenceError,
    SequenceExecutor,
    match_nodes,
    parse_bounds,
    parse_ui_dump,
    select_node,
)
from custom_components.myhyundai_aircon.recipe import (
    Recipe,
    Sequence,
    Step,
)

WIDGET_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node text="" resource-id="" content-desc="" class="android.widget.FrameLayout" package="com.sec.android.app.launcher" bounds="[0,0][840,2289]">
    <node text="켜기" resource-id="com.hyundai.oneapp.kr:id/btn_climate" content-desc="" class="android.widget.Button" package="com.hyundai.oneapp.kr" bounds="[100,600][240,760]"/>
    <node text="잠금" resource-id="com.hyundai.oneapp.kr:id/btn_lock" content-desc="" class="android.widget.Button" package="com.hyundai.oneapp.kr" bounds="[250,600][390,760]"/>
    <node text="dup" resource-id="" content-desc="" class="android.widget.TextView" package="com.hyundai.oneapp.kr" bounds="[0,100][100,200]"/>
    <node text="dup" resource-id="" content-desc="" class="android.widget.TextView" package="com.hyundai.oneapp.kr" bounds="[0,300][100,400]"/>
    <node text="broken" resource-id="" content-desc="" class="x" package="x" bounds="garbage"/>
  </node>
</hierarchy>
"""

LOGIN_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node text="로그인" resource-id="" content-desc="" class="android.widget.Button" package="com.hyundai.oneapp.kr" bounds="[0,0][100,100]"/>
</hierarchy>
"""


class FakeAdbClient:
    """Records shell commands and serves canned responses."""

    def __init__(self, ui_xml: str = WIDGET_XML) -> None:
        self.commands: list[str] = []
        self.ui_xml = ui_xml
        self.screen_size = "840x2289"

    async def async_shell(self, command: str) -> str:
        self.commands.append(command)
        if command.startswith("uiautomator dump"):
            return self.ui_xml
        if "mWakefulness" in command:
            return "  mWakefulness=Awake\n"
        return ""

    async def async_get_screen_size(self) -> str:
        return self.screen_size


def _make_recipe(steps: list[Step], **kwargs) -> Recipe:
    """Wrap steps into a one-sequence recipe named 'seq'."""
    return Recipe(
        baseline_screen=kwargs.get("baseline_screen", "AUTO"),
        package="com.hyundai.oneapp.kr",
        login_markers=kwargs.get("login_markers", ()),
        sequences={
            "seq": Sequence(
                description="",
                steps=tuple(steps),
                has_placeholders=kwargs.get("has_placeholders", False),
            )
        },
    )


def _make_executor(
    steps: list[Step], client: FakeAdbClient | None = None, **kwargs
) -> tuple[SequenceExecutor, FakeAdbClient]:
    client = client or FakeAdbClient()
    executor = SequenceExecutor(
        client, _make_recipe(steps, **kwargs), "840x2289"
    )
    return executor, client


def _step(action: str, optional: bool = False, **params) -> Step:
    return Step(action=action, params=params, optional=optional)


def test_parse_bounds() -> None:
    """Bounds strings parse into coordinate tuples."""
    assert parse_bounds("[100,600][240,760]") == (100, 600, 240, 760)
    with pytest.raises(SequenceError):
        parse_bounds("garbage")


def test_parse_ui_dump_skips_broken_bounds() -> None:
    """Nodes without parseable bounds are dropped, not fatal."""
    nodes = parse_ui_dump(WIDGET_XML)
    assert len(nodes) == 5
    assert all(node.text != "broken" for node in nodes)


def test_match_and_select() -> None:
    """§8.4 matching: AND semantics, contains, and index pick."""
    nodes = parse_ui_dump(WIDGET_XML)
    button = select_node(
        nodes,
        {
            "text_contains": "켜",
            "package": "com.hyundai.oneapp.kr",
        },
    )
    assert button.resource_id == "com.hyundai.oneapp.kr:id/btn_climate"
    assert button.center == (170, 680)
    assert len(match_nodes(nodes, {"text": "dup"})) == 2
    second = select_node(nodes, {"text": "dup", "index": 1})
    assert second.bounds == (0, 300, 100, 400)
    with pytest.raises(SequenceError) as err:
        select_node(nodes, {"text": "없는버튼"})
    assert err.value.code == ERR_UNKNOWN_SCREEN


async def test_tap_node_taps_center() -> None:
    """tap_node dumps the UI and taps the node's center point."""
    executor, client = _make_executor(
        [_step("tap_node", match={"text": "켜기"}, timeout=0)]
    )
    result = await executor.async_run_sequence("seq")
    assert result["result"] == "success"
    assert "input tap 170 680" in client.commands


async def test_assert_screen_mismatch() -> None:
    """A resolution drift fails with E_SCREEN_MISMATCH."""
    executor, client = _make_executor([_step("assert_screen")])
    client.screen_size = "1812x2176"
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("seq")
    assert err.value.code == ERR_SCREEN_MISMATCH


async def test_optional_step_failure_continues() -> None:
    """An optional step's failure does not abort the sequence."""
    executor, client = _make_executor(
        [
            _step(
                "tap_node",
                optional=True,
                match={"text": "없는버튼"},
                timeout=0,
            ),
            _step("keyevent", key="KEYCODE_HOME"),
        ]
    )
    result = await executor.async_run_sequence("seq")
    assert result["result"] == "success"
    assert "input keyevent KEYCODE_HOME" in client.commands


async def test_login_marker_raises_session_expired() -> None:
    """A login marker on screen maps to E_SESSION_EXPIRED."""
    executor, _ = _make_executor(
        [_step("wait_node", match={"text": "켜기"}, timeout=0)],
        client=FakeAdbClient(ui_xml=LOGIN_XML),
        login_markers=("로그인",),
    )
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("seq")
    assert err.value.code == ERR_SESSION_EXPIRED


async def test_placeholder_sequence_refused() -> None:
    """Sequences flagged incomplete refuse to run."""
    executor, _ = _make_executor([_step("wake")], has_placeholders=True)
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("seq")
    assert err.value.code == ERR_RECIPE_INCOMPLETE


async def test_unknown_sequence_refused() -> None:
    """A sequence key the recipe lacks is a distinct error."""
    executor, _ = _make_executor([_step("wake")])
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("missing")
    assert err.value.code == ERR_UNKNOWN_SEQUENCE


async def test_concurrent_run_hits_cooldown() -> None:
    """A second run while one is active returns E_COOLDOWN."""
    executor, _ = _make_executor([_step("sleep", seconds=0.3)])
    task = asyncio.create_task(executor.async_run_sequence("seq"))
    await asyncio.sleep(0.05)
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("seq")
    assert err.value.code == ERR_COOLDOWN
    assert (await task)["result"] == "success"


async def test_await_notification_not_implemented_yet() -> None:
    """The step is schema-valid but refuses until stage 6 lands."""
    executor, _ = _make_executor(
        [
            _step(
                "await_notification",
                success_contains=["ok"],
                failure_contains=[],
                timeout=1,
            )
        ]
    )
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("seq")
    assert err.value.code == ERR_NOT_IMPLEMENTED
