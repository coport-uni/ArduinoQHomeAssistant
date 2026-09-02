"""Tests for the UNO Q RGB LED colour mapping (apps/ha-mcu-bridge)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "apps/ha-mcu-bridge/python")
)

from led_color import (  # noqa: E402
    CHANNEL_MAX,
    ON_OFF_THRESHOLD,
    quantize_rgb,
    scale_rgb,
)


def test_scale_rgb_at_full_brightness_is_the_colour_itself():
    assert scale_rgb((255, 128, 0), CHANNEL_MAX) == (255, 128, 0)


def test_scale_rgb_halves_every_channel_at_half_brightness():
    # 128/255 is a hair over half, so 200 rounds to 100 and 100 to 50.
    assert scale_rgb((200, 100, 0), 128) == (100, 50, 0)


def test_scale_rgb_at_zero_brightness_is_off():
    assert scale_rgb((255, 255, 255), 0) == (0, 0, 0)


def test_scale_rgb_clamps_out_of_range_input():
    assert scale_rgb((300, -20, 255), 999) == (255, 0, 255)


def test_scale_rgb_rejects_wrong_channel_count():
    with pytest.raises(ValueError):
        scale_rgb((255, 255), CHANNEL_MAX)


def test_quantize_rgb_rounds_each_channel_to_the_rail():
    assert quantize_rgb((200, 100, 0)) == (255, 0, 0)


def test_quantize_rgb_is_inclusive_at_the_threshold():
    assert quantize_rgb((ON_OFF_THRESHOLD, ON_OFF_THRESHOLD - 1, 0)) == (
        255,
        0,
        0,
    )


def test_quantize_rgb_reaches_all_eight_combinations():
    corners = {
        quantize_rgb((r, g, b))
        for r in (0, 255)
        for g in (0, 255)
        for b in (0, 255)
    }
    assert len(corners) == 8


def test_quantize_rgb_rejects_wrong_channel_count():
    with pytest.raises(ValueError):
        quantize_rgb((255, 255, 255, 255))


def test_dimming_led4_drops_channels_rather_than_dimming_them():
    """LED4 has no PWM, so brightness can only remove channels."""
    scaled = scale_rgb((255, 255, 255), 100)
    assert quantize_rgb(scaled) == (0, 0, 0)
    scaled = scale_rgb((255, 255, 255), 200)
    assert quantize_rgb(scaled) == (255, 255, 255)
