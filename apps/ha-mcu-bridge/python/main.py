"""Bridge UNO Q on-board LEDs to Home Assistant via MQTT Discovery.

Publishes the two RGB user LEDs as MQTT JSON lights and, optionally,
one MQTT switch per entry in PIN_CONFIG for the D2-D13 header pins.
Commands received over MQTT are forwarded to the MCU sketch through the
Arduino router Bridge RPC. States are echoed back on retained state
topics so Home Assistant stays in sync.

LED3 has PWM channels behind it and gets true 24-bit colour plus
brightness; LED4 is GPIO-only, so its colour collapses to the eight
on/off combinations (see led_color.quantize_rgb).

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
from led_color import CHANNEL_MAX, quantize_rgb, scale_rgb

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

# The two on-board RGB user LEDs. "quantize" marks the GPIO-only one:
# its scaled colour is rounded to on/off per channel, so lowering
# brightness dims it by dropping channels rather than smoothly.
LIGHT_CONFIG = {
    "led3": {"name": "LED3", "rpc": "set_led3_rgb", "quantize": False},
    "led4": {"name": "LED4", "rpc": "set_led4_rgb", "quantize": True},
}

# Header pins exposed to Home Assistant as plain switches. Commented
# out on purpose -- enable only the ones whose wiring you know is safe
# to drive. The LED pins are NOT available here: LED3 must never be
# touched by the GPIO API or its PWM stops working until an MCU reset.
PIN_CONFIG = {
    # "D13": {"active_low": False},
    # "D12": {"active_low": False},
}


class HaMcuBridge:
    """Bridge the on-board LEDs and load stats to MQTT.

    run() is the only public method. The _handle_* methods are MQTT
    callbacks invoked by paho-mqtt, and the remaining underscore
    methods are internal helpers.
    """

    def __init__(self):
        """Create the MQTT client and register its callbacks."""
        self._lock = threading.Lock()
        self._lights = {
            name: {
                "state": "OFF",
                "brightness": CHANNEL_MAX,
                "color": {
                    "r": CHANNEL_MAX,
                    "g": CHANNEL_MAX,
                    "b": CHANNEL_MAX,
                },
            }
            for name in LIGHT_CONFIG
        }
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
        """Announce discovery, availability, and initial states."""
        print(f"MQTT connected: {reason_code}")
        self._publish_discovery()
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)
        for name in LIGHT_CONFIG:
            client.subscribe(self._build_command_topic(name))
            # The sketch turns both LEDs off in setup().
            self._publish_light_state(name)
        for name in PIN_CONFIG:
            client.subscribe(self._build_command_topic(name))
            client.publish(self._build_state_topic(name), "OFF", retain=True)

    def _handle_message(self, client, userdata, msg):
        """Apply one command from Home Assistant to its LED or pin."""
        name = msg.topic.split("/")[1]
        try:
            if name in LIGHT_CONFIG:
                self._apply_light(name, json.loads(msg.payload.decode()))
                self._publish_light_state(name)
            elif name in PIN_CONFIG:
                self._apply_pin(name, msg.payload.decode().strip().upper())
        except Exception as e:
            print(f"Bridge call failed for {name}: {e}")

    # -- Internal helpers ------------------------------------------------

    def _build_command_topic(self, name):
        """Return the MQTT command topic for one LED or pin name."""
        return f"{BASE_TOPIC}/{name}/set"

    def _build_state_topic(self, name):
        """Return the MQTT state topic for one LED or pin name."""
        return f"{BASE_TOPIC}/{name}/state"

    def _apply_light(self, name, command):
        """Merge one JSON light command into state and drive the LED."""
        light = self._lights[name]
        light["state"] = command.get("state", light["state"]).upper()
        if "brightness" in command:
            light["brightness"] = command["brightness"]
        if "color" in command:
            light["color"] = {
                channel: command["color"].get(channel, 0)
                for channel in ("r", "g", "b")
            }

        if light["state"] == "ON":
            colour = tuple(light["color"][c] for c in ("r", "g", "b"))
            duty = scale_rgb(colour, light["brightness"])
            if LIGHT_CONFIG[name]["quantize"]:
                duty = quantize_rgb(duty)
        else:
            duty = (0, 0, 0)

        with self._lock:
            Bridge.call(LIGHT_CONFIG[name]["rpc"], *duty)
        print(f"{name} -> {light['state']} {duty}")

    def _apply_pin(self, name, payload):
        """Forward one ON/OFF switch command to a header pin."""
        logical_on = payload == "ON"
        hw_state = (
            (not logical_on) if PIN_CONFIG[name]["active_low"] else logical_on
        )
        with self._lock:
            Bridge.call("set_pin_by_name", name, hw_state)
        self._client.publish(
            self._build_state_topic(name),
            "ON" if logical_on else "OFF",
            retain=True,
        )
        print(f"{name} -> {'ON' if logical_on else 'OFF'}")

    def _publish_light_state(self, name):
        """Echo one light's full state on its retained state topic."""
        light = self._lights[name]
        payload = {
            "state": light["state"],
            "brightness": light["brightness"],
            "color_mode": "rgb",
            "color": light["color"],
        }
        self._client.publish(
            self._build_state_topic(name), json.dumps(payload), retain=True
        )

    def _publish_discovery(self):
        """Publish one retained MQTT Discovery config per entity."""
        device = {
            "identifiers": ["unoq_mcu_bridge"],
            "name": "UNO Q MCU",
            "manufacturer": "Arduino",
            "model": "UNO Q (STM32U585)",
        }
        for name, spec in LIGHT_CONFIG.items():
            config = {
                "name": spec["name"],
                "unique_id": f"unoq_{name}",
                "schema": "json",
                "brightness": True,
                "supported_color_modes": ["rgb"],
                "command_topic": self._build_command_topic(name),
                "state_topic": self._build_state_topic(name),
                "availability_topic": AVAILABILITY_TOPIC,
                "device": device,
            }
            self._client.publish(
                f"{DISCOVERY_PREFIX}/light/unoq_{name}/config",
                json.dumps(config),
                retain=True,
            )
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
        skips one frame and can never take down the MQTT light side.
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
