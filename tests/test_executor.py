"""Unit tests for the myhyundai_aircon sequence executor."""

import asyncio

import pytest

from custom_components.myhyundai_aircon.const import (
    ERR_COOLDOWN,
    ERR_RECIPE_INCOMPLETE,
    ERR_SCREEN_MISMATCH,
    ERR_SESSION_EXPIRED,
    ERR_TIMEOUT,
    ERR_UNKNOWN_SCREEN,
    ERR_UNKNOWN_SEQUENCE,
    ERR_VEHICLE_FAIL,
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


def _notification_dump(records: list[tuple[str, str]]) -> str:
    """Build dumpsys-notification output in the observed format.

    Args:
        records: (id, text) pairs for com.hyundai.oneapp.kr.
    """
    lines = ["  mNotificationList:"]
    for record_id, text in records:
        lines.append(
            "    NotificationRecord(0xabc: pkg=com.hyundai.oneapp.kr"
            f" user=UserHandle{{0}} id={record_id} tag=null"
            f" key=0|com.hyundai.oneapp.kr|{record_id}|null|10321:"
            " Notification(channel=fcm_default_channel))"
        )
        lines.append(f"            tickerText={text}")
        lines.append(f"                android.text=String ({text})")
    return "\n".join(lines) + "\n"


class FakeAdbClient:
    """Records shell commands and serves canned responses."""

    def __init__(self, ui_xml: str = WIDGET_XML) -> None:
        self.commands: list[str] = []
        self.ui_xml = ui_xml
        self.screen_size = "840x2289"
        # Consumed one per dumpsys-notification call; the last one
        # keeps repeating so polls can outnumber fixtures.
        self.notification_dumps: list[str] = [_notification_dump([])]

    async def async_shell(self, command: str) -> str:
        self.commands.append(command)
        if command.startswith("uiautomator dump"):
            return self.ui_xml
        if "mWakefulness" in command:
            return "  mWakefulness=Awake\n"
        if "dumpsys notification" in command:
            if len(self.notification_dumps) > 1:
                return self.notification_dumps.pop(0)
            return self.notification_dumps[0]
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


def _await_step(**overrides) -> Step:
    """An await_notification step with observed real markers."""
    params = {
        "success_contains": ["공조가 켜졌습니다"],
        "failure_contains": ["실패"],
        "timeout": 5,
    }
    params.update(overrides)
    return _step("await_notification", **params)


async def test_await_notification_success() -> None:
    """A new success record ends the sequence with its text."""
    executor, client = _make_executor([_await_step()])
    client.notification_dumps = [
        _notification_dump([("100", "지난 알림")]),
        _notification_dump(
            [("100", "지난 알림"), ("200", "공조가 켜졌습니다.")]
        ),
    ]
    result = await executor.async_run_sequence("seq")
    assert result["result"] == "success"
    assert result["notification_text"] == "공조가 켜졌습니다."


async def test_await_notification_failure_first() -> None:
    """A failure marker wins even alongside a success marker."""
    executor, client = _make_executor([_await_step()])
    client.notification_dumps = [
        _notification_dump([]),
        _notification_dump([("200", "공조가 켜졌습니다 실패했습니다")]),
    ]
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("seq")
    assert err.value.code == ERR_VEHICLE_FAIL


async def test_await_notification_ignores_stale_records() -> None:
    """A record already present at start never counts as a result."""
    stale = _notification_dump([("100", "공조가 켜졌습니다.")])
    executor, client = _make_executor([_await_step(timeout=0)])
    client.notification_dumps = [stale]
    with pytest.raises(SequenceError) as err:
        await executor.async_run_sequence("seq")
    assert err.value.code == ERR_TIMEOUT
