# ArduinoQTest — Home Assistant + Smart Plug + MCU Control on Arduino UNO Q

This repository documents a working smart-home test rig built entirely on
a single **Arduino UNO Q** board:

- **Home Assistant** runs on the board itself (Docker container).
- Two **TP-Link Tapo P110M** smart plugs are discovered, registered, and
  controlled through Home Assistant, including live power monitoring.
- The board's own **STM32U585 MCU pins** (on-board RGB LEDs, optionally
  header pins D2–D13) appear in Home Assistant as switches, wired
  through MQTT and the UNO Q's internal Linux↔MCU RPC bridge.
- Everything is driven remotely from a host PC over **WiFi (SSH)**.
  USB/ADB is used exactly once, to join WiFi and enable SSH — after
  that the USB port stays free for expansion devices such as a Zigbee
  dongle.

All procedures were verified end-to-end on real hardware (see
[Verified results](#verified-results)).

## If you know the UNO R4, read this first

The UNO Q shares the classic UNO form factor and pinout, but it is a
fundamentally different machine. The mental model from the R4 does not
transfer directly:

| | UNO R4 (Minima/WiFi) | UNO Q |
|---|---|---|
| Brain | One MCU (Renesas RA4M1, + ESP32-S3 for WiFi) | **Two brains**: Qualcomm Dragonwing QRB2210 (4× Cortex-A53) running full **Debian 13 Linux**, plus an STM32U585 MCU (Cortex-M33, 2 MB flash) driving the headers |
| Operating system | None — your sketch IS the firmware | Linux boots first (~30 s); the MCU runs its own sketch alongside |
| USB port | Serial/DFU for sketch upload | **ADB port** (like an Android phone). `adb shell` drops you into Debian as user `arduino` |
| Sketch upload | From your PC via IDE/USB | **Compiled and flashed ON the board itself** (`arduino-cli` + Zephyr-based core `arduino:zephyr:unoq`; flashing goes through on-board OpenOCD over SWD). Your PC never talks to the MCU directly |
| Programming unit | A sketch | An **App Lab "app"** = `sketch/` (MCU) + `python/` (Linux) that talk to each other via an RPC bridge (`arduino-router`) |
| WiFi | ESP32-S3 co-processor, WiFiS3 library in the sketch | Linux owns WiFi (NetworkManager). The sketch has no network — the Python side does networking and calls the MCU when pins must move |
| Extra abilities | — | The Linux side runs **Docker**, Python 3.13, `gh`, OpenOCD… it is a small ARM computer (~4 GB RAM, ~10 GB eMMC) |
| Shield caution | 5 V logic | 3.3 V-class SoC + STM32 — verify voltage compatibility before reusing R4-era shields |

Two consequences that surprise R4 users most:

1. **You never "upload from the IDE over USB."** You copy the app onto
   the board (adb push / ssh) and ask the board to build and flash its
   own MCU: `arduino-app-cli app start <dir>`. First build takes a few
   minutes (Zephyr core), later ones ~100 s.
2. **The sketch and the Python program are a pair.** The sketch exposes
   functions with `Bridge.provide("name", fn)`; Linux Python calls them
   with `Bridge.call("name", args)`. One sketch runs at a time —
   starting another app re-flashes the MCU.

## What was built

```
                    Arduino UNO Q (single board)
┌───────────────────────────────────────────────────────────────┐
│  Debian Linux (QRB2210)                        STM32U585 MCU  │
│                                                               │
│  Home Assistant ── MQTT ── Mosquitto                          │
│   (Docker,          │       (Docker, host-local               │
│    port 8123)       │        listeners only)                  │
│                     │                                         │
│              ha-mcu-bridge app                                │
│              (python, paho-mqtt) ── Bridge RPC ──► sketch     │
│                                    (arduino-router) │         │
│                                                     ▼         │
│                                        RGB LEDs / D2–D13 pins │
└───────────────────────────────────────────────────────────────┘
          │ WiFi (TP-Link_0624, 192.168.1.0/24)
          ▼
   2× Tapo P110M smart plugs  ◄── tplink integration (KLAP auth)
```

- Home Assistant Container 2026.7.2, onboarded headlessly via REST API
  (no browser needed), long-lived API token minted over WebSocket.
- Tapo P110M plugs detected two independent ways (python-kasa subnet
  probe + HA tplink discovery), then registered with KLAP credentials.
  Full entity sets including voltage/current/energy sensors.
- `apps/ha-mcu-bridge/`: App Lab app exposing MCU pins to HA as MQTT
  switches with automatic discovery (no HA YAML edits). Defaults to the
  six on-board RGB LED channels; header pins are opt-in in
  `python/main.py` `PIN_CONFIG` for safety.
- The same app renders the Linux side's live CPU/memory load as bars
  on the on-board 8x13 LED matrix (psutil sampling every 2 s, pushed
  to the sketch over Bridge RPC; CPU on 2 rows, MEM on 3).

## Verified results

| Test | Result |
|---|---|
| Tapo detection (network + HA discovery) | 2/2 plugs found, methods agree |
| Tapo registration in HA | Both plugs, full entity sets, live 7.3 W load reading |
| Tapo relay toggle via HA, 3 s cadence | 6/6 transitions OK, ~1 s latency |
| MCU LED toggle via HA → MQTT → RPC, 3 s cadence | 6/6 transitions OK, LED visibly blinking |
| System-load bars on the 8x13 LED matrix | Idle: CPU 1-2 cols, MEM ~5 cols (~35 %); 4-core `yes` stress grows the CPU bar and it shrinks back; HA switches keep passing 6/6 concurrently |

## Repository layout

| Path | What it is |
|---|---|
| `docs/home-assistant-uno-q-guide.md` | **Main guide**: step-by-step from the one-time ADB bootstrap to controlling MCU pins from HA over SSH, with troubleshooting. Start here. |
| `docs/uno-q-vscode-wifi-guide.md` | Developing the UNO Q over WiFi with VS Code Remote-SSH (no USB cable) |
| `apps/ha-mcu-bridge/` | App Lab app: MCU sketch (pin RPC) + Python MQTT bridge with HA Discovery |
| `apps/mosquitto/mosquitto.conf` | MQTT broker config (host-local listeners, nothing on the LAN) |
| `claude_test/` | Working diagnostic scripts (subnet Tapo probe, HA onboarding/auth/registration, toggle tester) — each documented in its README |
| `external/CommonClaude` | Shared engineering conventions (git submodule) |
| `CLAUDE.md`, `ToDo.md`, `LearnedPatterns.md` | Project conventions, cumulative task log, and lessons learned |

Clone with the submodule:

```bash
git clone --recurse-submodules https://github.com/coport-uni/ArduinoQTest.git
```

## Quick start (another UNO Q board)

Condensed from the main guide, but complete: every command a brand-new
board needs is below — read the guide for expected output and
troubleshooting. Prerequisites: a Linux host with `adb`/`ssh`/`scp`,
a 2.4 GHz WiFi network, and Tapo plugs already paired to that same
network via the Tapo app.

```bash
# 1. One-time USB bootstrap: check ADB, join WiFi, note the board IP.
adb devices -l
# Only if it prints "no permissions": add a udev rule once, retry.
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2341", MODE="0666", GROUP="plugdev"' \
  | sudo tee /etc/udev/rules.d/51-arduino-unoq.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
adb kill-server && adb devices
adb shell 'nmcli device wifi connect "<SSID>" password "<PW>"'
adb shell 'ip -4 addr show wlan0 | grep inet'   # note <BOARD_IP>

# 2. Enable SSH and install your public key (run ssh-keygen -t
#    ed25519 first if you have no key). Fresh images ship sshd
#    WITHOUT host keys, so SSH is refused until they are generated;
#    root access uses the privileged-helper trick since `arduino`
#    has no passwordless sudo. Then unplug USB — WiFi only from here.
adb shell "docker run --rm --privileged --pid=host python:3.12-alpine \
  nsenter -t 1 -m -u -i -n -p -- \
  sh -c 'ssh-keygen -A && systemctl restart ssh'"
PUB=$(cat ~/.ssh/id_ed25519.pub)
adb shell "mkdir -p ~/.ssh && chmod 700 ~/.ssh \
  && echo '$PUB' >> ~/.ssh/authorized_keys \
  && chmod 600 ~/.ssh/authorized_keys"
printf 'Host unoq\n  HostName <BOARD_IP>\n  User arduino\n  Port 22\n' \
  >> ~/.ssh/config
ssh unoq hostname   # prints the board hostname, no password prompt

# 3. Home Assistant (image pull takes minutes; first boot 1-2 min)
ssh unoq 'mkdir -p /home/arduino/homeassistant && docker run -d \
  --name homeassistant --restart=unless-stopped --privileged \
  -e TZ=Asia/Seoul -v /home/arduino/homeassistant:/config \
  -v /run/dbus:/run/dbus:ro --network=host \
  ghcr.io/home-assistant/home-assistant:stable'

# 4. Onboard + long-lived token (scripts from claude_test/)
scp claude_test/{ha_onboard.sh,ha_login.sh} unoq:/home/arduino/
scp claude_test/mint_ll.py unoq:/tmp/
ssh unoq 'HA_USER=arduino HA_PASS=<pw> bash /home/arduino/ha_onboard.sh'
ssh unoq 'HA_PASS=<pw> bash /home/arduino/ha_login.sh'

# 5. Tapo plugs: find their MACs on your /24 (replace 192.168.1),
#    then register each one. KLAP auth needs your TP-Link account
#    email+password in EXACT case; detection alone does not.
scp claude_test/probe_all.py unoq:/tmp/
ssh unoq 'docker run --rm --network=host \
  -v /tmp/probe_all.py:/probe.py python:3.12-alpine \
  sh -c "pip install -q python-kasa && python /probe.py 192.168.1"'
scp claude_test/ha_add_tapo.sh unoq:/home/arduino/
ssh unoq 'TAPO_USER=<email> TAPO_PASS=<pw> \
  bash /home/arduino/ha_add_tapo.sh <PLUG_MAC>'   # repeat per plug

# 6. MCU bridge: Mosquitto broker + HA MQTT integration + App Lab
#    app. First build+flash takes a few minutes (Zephyr core, SWD);
#    the "default" property makes the app auto-start after reboots.
ssh unoq 'mkdir -p /home/arduino/mosquitto'
scp apps/mosquitto/mosquitto.conf unoq:/home/arduino/mosquitto/
ssh unoq 'docker run -d --name mosquitto --restart=unless-stopped \
  --network=host -v /home/arduino/mosquitto:/mosquitto/config \
  eclipse-mosquitto:2'
scp claude_test/ha_add_mqtt.sh unoq:/home/arduino/
ssh unoq 'bash /home/arduino/ha_add_mqtt.sh'
scp -r apps/ha-mcu-bridge unoq:/home/arduino/ArduinoApps/
ssh unoq 'arduino-app-cli app start \
  /home/arduino/ArduinoApps/ha-mcu-bridge'
ssh unoq 'arduino-app-cli properties set default \
  /home/arduino/ArduinoApps/ha-mcu-bridge'

# 7. Verify: list the switch entities HA created, then toggle a plug
#    and an MCU LED end-to-end. The LED matrix should already be
#    showing the CPU (2 rows) / MEM (3 rows) load bars.
ssh unoq 'curl -s http://localhost:8123/api/states \
  -H "Authorization: Bearer $(cat /home/arduino/.ha_token)" \
  | python3 -c "import sys,json
for e in json.load(sys.stdin):
    if e[\"entity_id\"].startswith(\"switch.\"): print(e[\"entity_id\"])"'
ssh unoq 'bash -s -- switch.<plug_entity> 3' \
  < claude_test/toggle_test.sh
ssh unoq 'bash -s -- switch.uno_q_mcu_uno_q_led3_g 3' \
  < claude_test/toggle_test.sh
```

CAUTION for step 7: toggling a plug power-cycles whatever is plugged
into it, and a plug whose relay is off always reports 0 W even with a
load attached — make sure the socket is safe to cycle (guide step 8).

## Gotchas discovered on real hardware

The full list lives in the guide's troubleshooting table; the ones that
cost the most time:

- **adb + app builds** (only if you fall back to adb instead of SSH):
  adbd sets Android-style `TMPDIR=/data/local/tmp` which does not exist
  on Debian — app builds die with `Stat /Data/Local/Tmp`. Prefix with
  `TMPDIR=/tmp`. Over SSH this does not apply.
- **App Lab networking**: app Python runs in a *bridged* Docker
  container — `127.0.0.1` is the container, not the board. Services it
  must reach (like the MQTT broker) need a listener on `172.17.0.1`.
- **Tapo KLAP auth** is case-sensitive for *both* email and password,
  and detection works anonymously but any control requires the TP-Link
  account credentials.
- **A ping/ARP sweep is not a Tapo detector** — some plugs ignore ICMP.
  Unicast discovery on every subnet IP (`claude_test/probe_all.py`) is
  reliable.
- **HA onboarding tokens expire in ~30 min**; mint a long-lived token
  over the WebSocket API early (`claude_test/ha_login.sh`).

## Conventions

This repo follows the [CommonClaude](https://github.com/coport-uni/CommonClaude)
ruleset (vendored as a submodule, applied via `CLAUDE.md` and Claude
Code hooks): Conventional Commits, append-only `ToDo.md` task log,
throwaway diagnostics quarantined in `claude_test/`, Ruff-clean Python.
