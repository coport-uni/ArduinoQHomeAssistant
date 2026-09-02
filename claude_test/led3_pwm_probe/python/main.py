"""HTTP driver for the LED3 PWM probe (issue #40).

Endpoints (GET, all on port 8766):
    /pwm?r=&g=&b=        analogWrite only, pad never GPIO-configured
    /pwm_after_gpio?...  pinMode(OUTPUT) first, then analogWrite
    /gpio?r=&g=&b=       digitalWrite control path (0/1 per channel)
    /ramp?ch=0&secs=6    slow 0->255->0 sweep on one channel via
                         analogWrite; a visible breathing effect proves
                         PWM reaches the pad
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from arduino.app_utils import App, Bridge

RAMP_STEPS = 64

_lock = threading.Lock()


def _call(name, r, g, b):
    with _lock:
        Bridge.call(name, r, g, b)


def _ramp(channel, seconds):
    """Breathe one LED3 channel so PWM is visually unmistakable."""
    values = [0, 0, 0]
    delay = seconds / (2.0 * RAMP_STEPS)
    for step in list(range(RAMP_STEPS + 1)) + list(
        range(RAMP_STEPS - 1, -1, -1)
    ):
        values[channel] = round(255 * step / RAMP_STEPS)
        _call("pwm_raw", *values)
        time.sleep(delay)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        def arg(key, default=0):
            return int(query.get(key, [str(default)])[0])

        try:
            if parsed.path == "/pwm":
                _call("pwm_raw", arg("r"), arg("g"), arg("b"))
                body = {"ok": True, "mode": "pwm_raw"}
            elif parsed.path == "/pwm_after_gpio":
                _call("pwm_after_gpio", arg("r"), arg("g"), arg("b"))
                body = {"ok": True, "mode": "pwm_after_gpio"}
            elif parsed.path == "/gpio":
                _call("gpio_set", arg("r"), arg("g"), arg("b"))
                body = {"ok": True, "mode": "gpio"}
            elif parsed.path == "/info":
                with _lock:
                    body = {
                        "ok": True,
                        "led_builtin": Bridge.call("led_builtin_pin"),
                    }
            elif parsed.path == "/ramp":
                _ramp(arg("ch"), arg("secs", 6))
                body = {"ok": True, "mode": "ramp"}
            else:
                self.send_response(404)
                self.end_headers()
                return
            code = 200
        except Exception as e:
            body, code = {"ok": False, "error": str(e)}, 500

        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8766), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("led3_pwm_probe listening on 8766", flush=True)
    App.run()


if __name__ == "__main__":
    main()
