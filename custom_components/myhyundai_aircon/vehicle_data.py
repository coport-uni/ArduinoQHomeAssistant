"""Read-only vehicle data scraped from the MyHyundai widget.

The widget shows live vehicle state as plain text and
content-descriptions (verified on the real device 2026-09-01/02:
"93%", "367km", "차량 상태, 문잠김", "오전 8:07 기준",
"캐스퍼 Electric", an "업데이트 가능" icon). This module turns a
parsed UI-dump node list into a typed snapshot. Everything here is
tolerant: a missing or reworded field becomes None instead of an
error, so an app update degrades sensors to unknown rather than
breaking the integration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .executor import UiNode

_BATTERY_PATTERN = re.compile(r"^(\d{1,3})%$")
_RANGE_PATTERN = re.compile(r"^(\d+(?:,\d{3})*)\s*km$")
_TIME_PATTERN = re.compile(r"(오전|오후)\s*(\d{1,2}):(\d{2})\s*기준")
_VERSION_PATTERN = re.compile(r"versionName=(\S+)")

_DOORS_LOCKED_MARKER = "문잠김"
_DOORS_UNLOCKED_MARKER = "문열림"
_UPDATE_AVAILABLE_DESC = "업데이트 가능"

# Texts that are widget chrome, never the vehicle name.
_NON_NAME_TEXTS = {"켜기", "끄기", "잠금", "시작", "종료"}

# Allow small clock skew before deciding a timestamp without a date
# belongs to yesterday.
_FUTURE_SLACK = timedelta(minutes=5)


@dataclass(frozen=True)
class VehicleData:
    """One scraped snapshot of what the widget displays."""

    battery_pct: int | None = None
    range_km: int | None = None
    doors_locked: bool | None = None
    updated_at: datetime | None = None
    vehicle_name: str | None = None
    update_available: bool = False


def parse_widget_time(text: str, now: datetime) -> datetime | None:
    """Turn the widget's "오전 8:07 기준" into an aware datetime.

    The widget shows no date, so the time is anchored to ``now``'s
    date and rolled back one day when that would land in the
    future (vehicle data cannot be newer than the present).

    Args:
        text: Any text containing the Korean time marker.
        now: Aware reference time (test injection point).

    Returns:
        The aware datetime, or None when no marker is present.
    """
    found = _TIME_PATTERN.search(text)
    if not found:
        return None
    meridiem, hour_text, minute_text = found.groups()
    hour = int(hour_text) % 12
    if meridiem == "오후":
        hour += 12
    stamp = now.replace(
        hour=hour, minute=int(minute_text), second=0, microsecond=0
    )
    if stamp > now + _FUTURE_SLACK:
        stamp -= timedelta(days=1)
    return stamp


def parse_vehicle_data(
    nodes: list[UiNode], package: str, now: datetime
) -> VehicleData:
    """Extract the vehicle snapshot from a UI-dump node list.

    Args:
        nodes: Parsed nodes of a full-screen dump.
        package: The MyHyundai package; other nodes are ignored.
        now: Aware reference time for timestamp anchoring.
    """
    battery = None
    range_km = None
    doors = None
    updated_at = None
    name = None
    update_available = False
    for node in nodes:
        if node.package != package:
            continue
        text = node.text.strip()
        if text:
            if battery is None and (m := _BATTERY_PATTERN.match(text)):
                battery = int(m.group(1))
                continue
            if range_km is None and (m := _RANGE_PATTERN.match(text)):
                range_km = int(m.group(1).replace(",", ""))
                continue
            if updated_at is None and (stamp := parse_widget_time(text, now)):
                updated_at = stamp
                continue
            if name is None and text not in _NON_NAME_TEXTS:
                name = text
        desc = node.content_desc
        if desc:
            if doors is None and _DOORS_LOCKED_MARKER in desc:
                doors = True
            elif doors is None and _DOORS_UNLOCKED_MARKER in desc:
                doors = False
            if desc == _UPDATE_AVAILABLE_DESC:
                update_available = True
    return VehicleData(
        battery_pct=battery,
        range_km=range_km,
        doors_locked=doors,
        updated_at=updated_at,
        vehicle_name=name,
        update_available=update_available,
    )


def parse_app_version(dumpsys_package_output: str) -> str | None:
    """Extract versionName from ``dumpsys package`` output."""
    found = _VERSION_PATTERN.search(dumpsys_package_output)
    return found.group(1) if found else None


_VEHICLE_IMAGE_DESC_PREFIX = "차량 상태"

# Climate-glow metric, calibrated on real cover-screen captures
# (2026-09-02): while remote climate runs, the widget draws a light
# blue aura around the car image. Fraction of matching pixels in
# the vehicle-image region measured 0.0151 when ON and exactly
# 0.0000 when OFF, so the threshold sits 3x under the ON signal.
GLOW_BLUE_MIN = 150
GLOW_BLUE_OVER_RED = 20
GLOW_THRESHOLD = 0.005


def find_vehicle_image_bounds(
    nodes: list[UiNode], package: str
) -> tuple[int, int, int, int] | None:
    """Locate the widget's vehicle-image region for glow analysis.

    The region is the node whose content-desc starts with
    "차량 상태" (the whole-widget container starts with "마이현대"
    instead, so it never matches).
    """
    for node in nodes:
        if node.package != package:
            continue
        if node.content_desc.startswith(_VEHICLE_IMAGE_DESC_PREFIX):
            return node.bounds
    return None


def measure_glow_fraction(
    screenshot_path: str, bounds: tuple[int, int, int, int]
) -> float | None:
    """Fraction of climate-glow pixels inside the given region.

    Blocking (file I/O + pixel scan) — call through an executor
    job. Returns None when Pillow is unavailable or the file cannot
    be read, so callers degrade to unknown instead of failing.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(screenshot_path) as image:
            region = image.convert("RGB").crop(bounds)
            pixels = list(region.getdata())
    except (OSError, ValueError):
        return None
    if not pixels:
        return None
    glow = sum(
        1
        for red, _green, blue in pixels
        if blue > GLOW_BLUE_MIN and blue > red + GLOW_BLUE_OVER_RED
    )
    return glow / len(pixels)
