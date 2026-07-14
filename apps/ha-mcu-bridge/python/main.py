"""Bridge UNO Q MCU pins to Home Assistant via MQTT Discovery.

Publishes one MQTT switch per entry in PIN_CONFIG. Commands received
over MQTT are forwarded to the MCU sketch through the Arduino router
Bridge RPC (set_pin_by_name). States are echoed back on retained
state topics so Home Assistant stays in sync.

A daemon thread also samples the Linux-side CPU and memory usage and
pushes them to the sketch (show_load RPC), which renders them as
horizontal bars on the on-board 8x13 LED matrix.

All behavior lives in the HaMcuBridge class: run() is the only
public entry point, and every other method is an internal detail
(prefixed with an underscore).
"""

import json
import os
import threading
import time

import paho.mqtt.client as mqtt
import psutil
from arduino.app_utils import App, Bridge

# App Lab apps run in bridged Docker containers, so host loopback is
# unreachable; the broker listens on docker0 (172.17.0.1) for us.
MQTT_HOST = os.environ.get("MQTT_HOST", "172.17.0.1")
MQTT_PORT = 1883
DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "unoq"
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/bridge/availability"

# LED matrix load display: push interval for the show_load RPC.
UPDATE_INTERVAL_S = 2.0

# Broker reconnect delay while the router network is still coming up.
RETRY_DELAY_S = 5

# Pins exposed to Home Assistant. The RGB user LEDs are safe defaults
# (nothing external is wired to them); header pins D2-D13 are
# commented out on purpose -- enable only the ones whose wiring you
# know is safe to drive.
PIN_CONFIG = {
    "LED3_R": {"active_low": True},
    "LED3_G": {"active_low": True},
    "LED3_B": {"active_low": True},
    "LED4_R": {"active_low": True},
    "LED4_G": {"active_low": True},
    "LED4_B": {"active_low": True},
    # "D13": {"active_low": False},
    # "D12": {"active_low": False},
}


class HaMcuBridge:
    """Bridge MCU pins and load stats between MQTT and the sketch.

    run() is the only public method. The _handle_* methods are MQTT
    callbacks invoked by paho-mqtt, and the remaining underscore
    methods are internal helpers.
    """

    def __init__(self):
        """Create the MQTT client and register its callbacks."""
        self._lock = threading.Lock()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._handle_connect
        self._client.on_message = self._handle_message
        self._client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)

    # -- Public API ----------------------------------------------------

    def run(self):
        """Connect to the broker, start the stats thread, and serve.

        Blocks forever inside App.run(); it does not return in normal
        operation.
        """
        while True:
            try:
                self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
                break
            except OSError as e:
                print(
                    f"MQTT broker not reachable at {MQTT_HOST}:{MQTT_PORT} "
                    f"({e}), retrying in {RETRY_DELAY_S} s"
                )
                time.sleep(RETRY_DELAY_S)
        self._client.loop_start()
        threading.Thread(target=self._push_stats_forever, daemon=True).start()
        App.run()

    # -- MQTT callbacks (invoked by paho-mqtt) ---------------------------

    def _handle_connect(self, client, userdata, flags, reason_code, props):
        """Announce discovery, availability, and initial pin states."""
        print(f"MQTT connected: {reason_code}")
        self._publish_discovery()
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)
        for name in PIN_CONFIG:
            client.subscribe(self._build_command_topic(name))
            # All pins start OFF (sketch setup() turns everything off).
            client.publish(self._build_state_topic(name), "OFF", retain=True)

    def _handle_message(self, client, userdata, msg):
        """Apply one ON/OFF command from Home Assistant to its pin."""
        name = msg.topic.split("/")[1]
        if name not in PIN_CONFIG:
            return
        payload = msg.payload.decode().strip().upper()
        logical_on = payload == "ON"
        try:
            self._apply_pin(name, logical_on)
            client.publish(
                self._build_state_topic(name),
                "ON" if logical_on else "OFF",
                retain=True,
            )
            print(f"{name} -> {'ON' if logical_on else 'OFF'}")
        except Exception as e:
            print(f"Bridge call failed for {name}: {e}")

    # -- Internal helpers ------------------------------------------------

    def _build_command_topic(self, name):
        """Return the MQTT command topic for one pin name."""
        return f"{BASE_TOPIC}/{name}/set"

    def _build_state_topic(self, name):
        """Return the MQTT state topic for one pin name."""
        return f"{BASE_TOPIC}/{name}/state"

    def _apply_pin(self, name, logical_on):
        """Forward one logical switch state to the MCU over Bridge RPC."""
        hw_state = (
            (not logical_on) if PIN_CONFIG[name]["active_low"] else logical_on
        )
        with self._lock:
            Bridge.call("set_pin_by_name", name, hw_state)

    def _publish_discovery(self):
        """Publish one retained MQTT Discovery config per pin."""
        device = {
            "identifiers": ["unoq_mcu_bridge"],
            "name": "UNO Q MCU",
            "manufacturer": "Arduino",
            "model": "UNO Q (STM32U585)",
        }
        for name in PIN_CONFIG:
            config = {
                "name": f"UNO Q {name}",
                "unique_id": f"unoq_mcu_{name.lower()}",
                "command_topic": self._build_command_topic(name),
                "state_topic": self._build_state_topic(name),
                "availability_topic": AVAILABILITY_TOPIC,
                "payload_on": "ON",
                "payload_off": "OFF",
                "device": device,
            }
            self._client.publish(
                f"{DISCOVERY_PREFIX}/switch/unoq_{name.lower()}/config",
                json.dumps(config),
                retain=True,
            )

    def _push_stats_forever(self):
        """Push CPU/memory percent to the MCU LED matrix forever.

        Runs as a daemon thread next to the MQTT loop. Every iteration
        is wrapped in try/except so a Bridge or psutil hiccup only
        skips one frame and can never take down the MQTT switch side.
        """
        # The first cpu_percent(None) call only primes psutil's internal
        # counters and returns a meaningless 0.0 -- discard it.
        psutil.cpu_percent(interval=None)
        time.sleep(UPDATE_INTERVAL_S)
        while True:
            try:
                cpu = round(psutil.cpu_percent(interval=None))
                mem = round(psutil.virtual_memory().percent)
                with self._lock:
                    Bridge.call("show_load", cpu, mem)
            except Exception as e:
                print(f"stats push failed: {e}", flush=True)
            time.sleep(UPDATE_INTERVAL_S)


def main():
    """Build the bridge and serve forever."""
    HaMcuBridge().run()


if __name__ == "__main__":
    main()
