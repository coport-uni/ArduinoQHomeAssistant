"""Grab one frame from the USB webcam pointed at the board.

Written to check LED colours on the real hardware while nobody is in
the room. OpenCV rather than ffmpeg: `ffmpeg -f dshow` on this host
refuses every explicit `-video_size`/`-framerate` combination with
"Could not set video options", and its default mode lands at 160x120,
which is too small to tell one LED from another.

The first frames off a C920 are under-exposed, so the capture keeps
reading for a couple of seconds and saves the last frame it got.

    python claude_test/cam_snap.py out.png [--index 0] [--seconds 2.5]
"""

import argparse
import time

import cv2

# Requested, not guaranteed: this C920 ignores both properties under
# the DSHOW backend and hands back 640x480 anyway, which is still
# enough to read one LED's colour.
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720

# Auto-exposure needs roughly this long to settle on a dim scene.
DEFAULT_WARMUP_S = 2.5


def capture(path, index, seconds):
    """Save one settled frame from the camera to path."""
    camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_HEIGHT)

    frame = None
    started = time.time()
    while time.time() - started < seconds:
        ok, latest = camera.read()
        if ok:
            frame = latest
    camera.release()

    if frame is None:
        raise SystemExit(f"no frame from camera {index}")
    cv2.imwrite(path, frame)
    print(f"saved {path} {frame.shape[1]}x{frame.shape[0]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="output image path")
    parser.add_argument("--index", type=int, default=0, help="camera index")
    parser.add_argument("--seconds", type=float, default=DEFAULT_WARMUP_S)
    args = parser.parse_args()
    capture(args.path, args.index, args.seconds)


if __name__ == "__main__":
    main()
