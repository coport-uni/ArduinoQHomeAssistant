"""Decode UNO Q LED-matrix frames to settle the raw matrixWrite bit order.

The official examples (weather-forecast, air-quality-monitoring) pass
4x uint32 frames straight to the firmware's matrixWrite(). This script
renders such a frame as an 8x13 grid under the two candidate bit
orders; whichever produces a recognizable icon is the raw format.
  A: pixel i = row*13+col -> word[i//32], bit (i % 32)   (LSB-first)
  B: pixel i = row*13+col -> word[i//32], bit (31 - i%32) (MSB-first)
"""

ROWS, COLS = 8, 13

# "good" frame from air-quality-monitoring (expected: a smiley face).
GOOD = [0x904101F0, 0x5F420212, 0x41390A28, 0x10]


def render(frame, msb_first):
    """Return the frame as lines of #/. under the given bit order."""
    lines = []
    for r in range(ROWS):
        line = ""
        for c in range(COLS):
            i = r * COLS + c
            bit = (31 - i % 32) if msb_first else (i % 32)
            line += "#" if frame[i // 32] >> bit & 1 else "."
        lines.append(line)
    return lines


if __name__ == "__main__":
    for label, msb in (("A: LSB-first", False), ("B: MSB-first", True)):
        print(label)
        print("\n".join(render(GOOD, msb)), end="\n\n")
