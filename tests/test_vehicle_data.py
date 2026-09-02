"""Unit tests for the widget vehicle-data parser.

The fixture mirrors the real cover-screen dump of 2026-09-02
(93 % / 367 km / 문잠김 / 오전 8:07 기준 / 캐스퍼 Electric).
"""

from datetime import datetime, timezone, timedelta

from custom_components.myhyundai_aircon.executor import parse_ui_dump
from custom_components.myhyundai_aircon.vehicle_data import (
    GLOW_THRESHOLD,
    find_vehicle_image_bounds,
    measure_glow_fraction,
    parse_app_version,
    parse_vehicle_data,
    parse_widget_time,
)

KST = timezone(timedelta(hours=9))
HYUNDAI_PKG = "com.hyundai.oneapp.kr"

VEHICLE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node text="" resource-id="" content-desc="마이현대, 위젯, 차량 상태, 문잠김" class="android.widget.LinearLayout" package="com.hyundai.oneapp.kr" bounds="[55,213][785,931]">
    <node text="오전 8:07 기준" resource-id="" content-desc="" class="android.widget.TextView" package="com.hyundai.oneapp.kr" bounds="[90,320][251,356]"/>
    <node text="" resource-id="" content-desc="업데이트 가능" class="android.widget.ImageView" package="com.hyundai.oneapp.kr" bounds="[251,321][286,356]"/>
    <node text="캐스퍼 Electric" resource-id="" content-desc="" class="android.widget.TextView" package="com.hyundai.oneapp.kr" bounds="[90,253][649,322]"/>
    <node text="" resource-id="" content-desc="차량 상태, 문잠김" class="android.widget.FrameLayout" package="com.hyundai.oneapp.kr" bounds="[90,365][750,666]"/>
    <node text="93%" resource-id="" content-desc="" class="android.widget.TextView" package="com.hyundai.oneapp.kr" bounds="[169,666][245,716]"/>
    <node text="367km" resource-id="" content-desc="" class="android.widget.TextView" package="com.hyundai.oneapp.kr" bounds="[291,666][401,716]"/>
    <node text="켜기" resource-id="" content-desc="" class="android.widget.TextView" package="com.hyundai.oneapp.kr" bounds="[140,851][185,888]"/>
  </node>
  <node text="100%" resource-id="" content-desc="" class="android.widget.TextView" package="com.android.systemui" bounds="[0,0][10,10]"/>
</hierarchy>
"""

NOW = datetime(2026, 9, 2, 8, 31, 0, tzinfo=KST)

DUMPSYS_PACKAGE_SNIPPET = (
    "    versionCode=1234 minSdk=29 targetSdk=35\n    versionName=5.3.1\n"
)


def test_parse_vehicle_data_full_snapshot() -> None:
    """All fields extract from the real-format widget dump."""
    nodes = parse_ui_dump(VEHICLE_XML)
    data = parse_vehicle_data(nodes, HYUNDAI_PKG, NOW)
    assert data.battery_pct == 93
    assert data.range_km == 367
    assert data.doors_locked is True
    assert data.updated_at == NOW.replace(
        hour=8, minute=7, second=0, microsecond=0
    )
    assert data.vehicle_name == "캐스퍼 Electric"
    assert data.update_available is True


def test_parse_ignores_other_packages() -> None:
    """The systemui 100% node must not become the battery value."""
    nodes = parse_ui_dump(VEHICLE_XML)
    data = parse_vehicle_data(nodes, HYUNDAI_PKG, NOW)
    assert data.battery_pct == 93


def test_parse_empty_dump_yields_unknowns() -> None:
    """No widget on screen degrades every field to None."""
    nodes = parse_ui_dump(
        "<hierarchy><node text='x' resource-id='' content-desc=''"
        " class='y' package='other' bounds='[0,0][1,1]'/></hierarchy>"
    )
    data = parse_vehicle_data(nodes, HYUNDAI_PKG, NOW)
    assert data.battery_pct is None
    assert data.range_km is None
    assert data.doors_locked is None
    assert data.updated_at is None
    assert data.vehicle_name is None
    assert data.update_available is False


def test_widget_time_meridiem_and_rollover() -> None:
    """오전/오후 parse correctly and future times roll back a day."""
    noonish = NOW.replace(hour=13)
    afternoon = parse_widget_time("오후 1:07 기준", noonish)
    assert (afternoon.hour, afternoon.minute) == (13, 7)
    midnightish = parse_widget_time("오전 12:05 기준", NOW)
    assert midnightish.hour == 0
    noon = parse_widget_time("오후 12:10 기준", NOW.replace(hour=23))
    assert noon.hour == 12
    # 11 PM data seen at 8:31 AM must be yesterday's.
    last_night = parse_widget_time("오후 11:50 기준", NOW)
    assert last_night.day == NOW.day - 1
    assert parse_widget_time("no marker", NOW) is None


def test_parse_app_version() -> None:
    """versionName is pulled from dumpsys package output."""
    assert parse_app_version(DUMPSYS_PACKAGE_SNIPPET) == "5.3.1"
    assert parse_app_version("nothing here") is None


def test_find_vehicle_image_bounds() -> None:
    """The 차량 상태 region is found; the 마이현대 container is not."""
    nodes = parse_ui_dump(VEHICLE_XML)
    assert find_vehicle_image_bounds(nodes, HYUNDAI_PKG) == (
        90,
        365,
        750,
        666,
    )
    assert find_vehicle_image_bounds(nodes, "com.other") is None


def _write_widget_image(path, glow: bool) -> None:
    """Paint a navy region, optionally with a light-blue aura band."""
    from PIL import Image

    navy = (27, 42, 74)
    image = Image.new("RGB", (100, 100), navy)
    if glow:
        aura = Image.new("RGB", (100, 10), (140, 190, 255))
        image.paste(aura, (0, 45))
    image.save(path)


def test_measure_glow_fraction(tmp_path) -> None:
    """The glow metric separates aura from plain navy background."""
    off_path = tmp_path / "off.png"
    on_path = tmp_path / "on.png"
    _write_widget_image(off_path, glow=False)
    _write_widget_image(on_path, glow=True)
    bounds = (0, 0, 100, 100)
    assert measure_glow_fraction(str(off_path), bounds) == 0.0
    on_fraction = measure_glow_fraction(str(on_path), bounds)
    assert on_fraction > GLOW_THRESHOLD
    assert measure_glow_fraction(str(tmp_path / "nope.png"), bounds) is None
