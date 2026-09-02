"""Colour maths shared by the UNO Q RGB LED lights.

Kept free of ``arduino``/``paho`` imports so the mapping can be unit
tested off the board. Home Assistant sends a colour and a brightness
separately; the LEDs need one number per channel, so brightness is
folded into the colour here rather than in the sketch.
"""

CHANNEL_MAX = 255

# A channel counts as lit once it reaches half scale. LED4 has no PWM
# behind it, so its colour has to collapse to one of eight on/off
# combinations and this is where the rounding happens.
ON_OFF_THRESHOLD = 128


def scale_rgb(rgb, brightness):
    """Fold a brightness level into an RGB colour.

    Args:
        rgb: Three 0-255 channel values as sent by Home Assistant.
        brightness: Overall 0-255 brightness for the light.

    Returns:
        Three 0-255 duty cycles, one per channel, ready for
        ``analogWrite`` on the MCU.

    Raises:
        ValueError: If ``rgb`` does not hold exactly three values.
    """
    if len(rgb) != 3:
        raise ValueError(f"expected 3 channels, got {len(rgb)}")
    level = _clamp(brightness)
    return tuple(round(_clamp(c) * level / CHANNEL_MAX) for c in rgb)


def quantize_rgb(rgb):
    """Reduce an RGB colour to the eight colours LED4 can actually show.

    Args:
        rgb: Three 0-255 channel values as sent by Home Assistant.

    Returns:
        Three values, each 0 or 255, forming the nearest of the eight
        on/off combinations.

    Raises:
        ValueError: If ``rgb`` does not hold exactly three values.
    """
    if len(rgb) != 3:
        raise ValueError(f"expected 3 channels, got {len(rgb)}")
    return tuple(
        CHANNEL_MAX if _clamp(c) >= ON_OFF_THRESHOLD else 0 for c in rgb
    )


def _clamp(value):
    """Clamp one channel or brightness value into 0-255."""
    return max(0, min(CHANNEL_MAX, int(value)))
