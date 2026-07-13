"""Heartbeat logger proving the Linux (MPU) side of the app runs.

Deployed and started over WiFi + SSH with arduino-app-cli; output is
visible via `arduino-app-cli app logs`.
"""

import time

heartbeat_interval_s = 5


def main():
    count = 0
    while True:
        count += 1
        print(f"qtest_blink heartbeat {count}", flush=True)
        time.sleep(heartbeat_interval_s)


if __name__ == "__main__":
    main()
