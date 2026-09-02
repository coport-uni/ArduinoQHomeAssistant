# Home Assistant on Arduino UNO Q — Setup, Tapo Integration & Control Guide

Reproducible procedure for provisioning any Arduino UNO Q board over
**WiFi/SSH**: install Home Assistant (HA) with Docker, detect TP-Link
Tapo P110M smart plugs, register them in HA (KLAP auth), and verify
end-to-end control with a timed on/off toggle test. A USB (ADB)
connection is needed **once**, to join WiFi and enable SSH; after that
the cable is removed and everything runs over the network. This keeps
the board's USB port free for expansion devices such as a Zigbee
dongle.

Verified on: Arduino UNO Q (Debian 13 trixie, aarch64, kernel 6.16),
Docker 26.1.5 on the board, Home Assistant Container 2026.7.2,
2x Tapo P110M(KR) — detection, registration, and a 6/6-pass toggle
test, all executed over SSH (2026-07-14).

## 0. Prerequisites

- Host PC (Linux) with `ssh`/`scp`, plus `adb` for the one-time
  bootstrap (step 1 only).
- Arduino UNO Q. The default Linux user is `arduino` and it is in the
  board's `docker` group (no sudo needed for Docker on the board).
- 2.4 GHz WiFi SSID + password for the board.
- Tapo P110M plugs already paired to the SAME WiFi network via the Tapo
  app, and powered on. (Pairing itself is done in the app; this guide
  only detects the plugs on the network.)
- ~2.5 GB free disk on the board (`df -h /`) for the HA image; ~1 GB RAM
  free while HA runs.

## 1. One-time bootstrap over ADB: USB permissions + WiFi

Connect the board to the host via USB just for this step.

```bash
adb devices -l
```

Expected: a device line such as
`2018875248  device usb:3-6 transport_id:1` (the UNO Q enumerates as USB
VID:PID `2341:0078`, product string "Uno Q - <hostname>").

### If it says `no permissions (missing udev rules?)`

Proper fix (needs sudo once):

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2341", MODE="0666", GROUP="plugdev"' \
  | sudo tee /etc/udev/rules.d/51-arduino-unoq.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
adb kill-server && adb devices
```

No-sudo workaround (host user must be in the `docker` group). Find the
bus/device number with `lsusb | grep 2341:0078` (e.g. Bus 003 Device 021),
then:

```bash
docker run --rm -v /dev/bus/usb:/dev/bus/usb alpine \
  chmod 666 /dev/bus/usb/003/021
adb kill-server && adb devices
```

Note: the workaround resets every time the board is re-plugged (the
device number also changes); the udev rule is permanent.

### Join the board to WiFi

Check current state first — the board may already be connected:

```bash
adb shell "nmcli device status; nmcli radio wifi"
```

If `wlan0` is not connected:

```bash
adb shell 'nmcli radio wifi on && nmcli device wifi rescan && sleep 3 && \
  nmcli device wifi connect "<SSID>" password "<PASSWORD>"'
```

Verify IP and internet:

```bash
adb shell "ip -4 addr show wlan0 | grep inet; ping -c 2 8.8.8.8"
```

Record the board IP (referred to as `<BOARD_IP>` below). The connection
persists across reboots (NetworkManager stores the profile).
Recommended: give the board a fixed DHCP lease in your router so the IP
never changes.

## 2. Enable SSH and switch to WiFi-only operation

Full details (fresh-image host-key fix, key installation, VS Code
Remote-SSH) live in `docs/uno-q-vscode-wifi-guide.md`; the short
version:

```bash
# 2a. Fresh images ship sshd without host keys — generate them once.
#     (Needs root; uses the privileged-helper trick since `arduino`
#     has no passwordless sudo but is in the docker group.)
adb shell "docker run --rm --privileged --pid=host python:3.12-alpine \
    nsenter -t 1 -m -u -i -n -p -- \
    sh -c 'ssh-keygen -A && systemctl restart ssh && systemctl is-active ssh'"

# 2b. Install your public key for passwordless login.
PUB=$(cat ~/.ssh/id_ed25519.pub)
adb shell "mkdir -p ~/.ssh && chmod 700 ~/.ssh \
    && grep -qF '$PUB' ~/.ssh/authorized_keys 2>/dev/null \
    || echo '$PUB' >> ~/.ssh/authorized_keys; \
    chmod 600 ~/.ssh/authorized_keys"
```

Add a host alias to `~/.ssh/config` on the host (adjust the IP; state
`Port 22` explicitly in case a global client config overrides it):

```
Host unoq
    HostName <BOARD_IP>
    User arduino
    Port 22
```

Verify, then unplug the USB cable — it is no longer needed:

```bash
ssh unoq hostname   # prints the board hostname, no password prompt
```

Every command below runs from the host over WiFi: `ssh unoq '<cmd>'`
executes on the board, `scp <file> unoq:<path>` copies files to it.
(This repo's board is aliased `sungwooq`; substitute your own alias.)

## 3. Install Home Assistant with Docker

The UNO Q image ships with Docker preinstalled and the `arduino` user in
the `docker` group. Host networking is REQUIRED for HA device discovery
(DHCP/mDNS/SSDP/UDP broadcasts).

```bash
ssh unoq 'mkdir -p /home/arduino/homeassistant && \
  docker run -d --name homeassistant --restart=unless-stopped --privileged \
    -e TZ=Asia/Seoul \
    -v /home/arduino/homeassistant:/config \
    -v /run/dbus:/run/dbus:ro \
    --network=host \
    ghcr.io/home-assistant/home-assistant:stable'
```

The image pull takes several minutes on WiFi (~20 layers). Then:

```bash
ssh unoq "docker ps --format '{{.Names}} {{.Status}}'; \
  curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8123"
```

`HTTP 302` = HA is up and waiting for onboarding; `HTTP 200` = onboarding
already done. First boot takes 1–2 minutes after the container starts.

## 4. Onboarding (create the HA owner account)

Option A — browser: open `http://<BOARD_IP>:8123` and follow the wizard.

Option B — scripted (no browser), using `claude_test/ha_onboard.sh`:

```bash
scp claude_test/ha_onboard.sh unoq:/home/arduino/ha_onboard.sh
ssh unoq 'HA_USER=arduino HA_PASS=<choose-a-password> \
  bash /home/arduino/ha_onboard.sh'
```

The script creates the owner user, completes the core_config / analytics
/ integration onboarding steps, and saves an API access token to
`/home/arduino/.ha_token` on the board (used by all verification calls
below). Expected output ends with all four steps `"done": true` and
`{"message": "API running."}`.

Caveat: the saved token is a normal OAuth access token and expires
(~30 min). Replace it with a long-lived token right away (step 6) so
later API calls do not start failing with 401 mid-procedure.

## 5. Verify: detect the Tapo P110M plugs

Two independent checks. Run both; they should agree.

### 5a. Network-level check (python-kasa, from the board)

```bash
scp claude_test/probe_all.py unoq:/tmp/probe_all.py
ssh unoq 'docker run --rm --network=host \
  -v /tmp/probe_all.py:/probe.py python:3.12-alpine \
  sh -c "pip install -q python-kasa && python /probe.py 192.168.1"'
```

Replace `192.168.1` with the board's actual /24 prefix. Expected:

```
TAPO/KASA devices found: 2
  192.168.1.239  P110M(KR)  18:69:45:71:05:2F
  192.168.1.79   P110M(KR)  18:69:45:71:02:7C
```

`auth-required` instead of a model name is also a PASS — it means a
KLAP-encrypted Tapo device answered but needs account credentials for
details. This probe sends unicast discovery to every IP in the subnet,
so it also finds plugs that ignore ping (an ARP/ping sweep is NOT a
reliable test for Tapo devices).

### 5b. Home Assistant-level check (tplink integration discovery)

```bash
ssh unoq 'TOKEN=$(cat /home/arduino/.ha_token)
resp=$(curl -s --max-time 180 -X POST \
  http://localhost:8123/api/config/config_entries/flow \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"handler\":\"tplink\"}")
fid=$(echo "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin)[\"flow_id\"])")
curl -s --max-time 120 -X POST \
  http://localhost:8123/api/config/config_entries/flow/$fid \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{}" | python3 -m json.tool
curl -s -X DELETE \
  http://localhost:8123/api/config/config_entries/flow/$fid \
  -H "Authorization: Bearer $TOKEN" -o /dev/null'
```

The first call can take up to a minute on first run (HA pip-installs
python-kasa on demand). PASS = the `pick_device` step lists both plugs:

```json
"options": [
  ["18:69:45:71:05:2f", "052F P110M (192.168.1.239) 18:69:45:71:05:2f"],
  ["18:69:45:71:02:7c", "027C P110M (192.168.1.79) 18:69:45:71:02:7c"]
]
```

This proves HA itself (not just the network) sees both P110Ms. The
trailing DELETE aborts the flow so no half-configured entry is left
behind. To actually ADD the plugs to HA, pick a device instead of
deleting the flow and supply your TP-Link (Tapo) account email/password
when prompted — P110M firmware uses KLAP authentication, so detection
works anonymously but control requires credentials.

## 6. Replace the expiring token with a long-lived one

The onboarding token dies after ~30 minutes, which is shorter than this
whole procedure. Mint a 10-year long-lived token (HA only issues these
over its WebSocket API; the board's system python has no aiohttp, so the
minting script runs inside the HA container):

```bash
scp claude_test/mint_ll.py unoq:/tmp/mint_ll.py
scp claude_test/ha_login.sh unoq:/home/arduino/ha_login.sh
ssh unoq 'HA_PASS=<HA-owner-password> bash /home/arduino/ha_login.sh'
```

Expected output ends with `long-lived token stored` and
`{"message":"API running."}`. The token overwrites
`/home/arduino/.ha_token`; every later step keeps reading it from there.

## 7. Register the plugs in Home Assistant

Detection (step 5) works anonymously, but ADDING a P110M requires your
TP-Link (Tapo) account credentials: the plug firmware uses KLAP, whose
local handshake is derived from the account email + password. Both are
CASE-SENSITIVE.

Optional but recommended — verify the credentials directly against a
plug first (fails in seconds, much faster feedback than the HA flow):

```bash
ssh unoq 'docker run --rm --network=host python:3.12-alpine sh -c \
  "pip install -q python-kasa && \
   kasa --host <PLUG_IP> --username <email> --password <password> state"'
```

PASS = a `== <name> - P110M ==` state dump. `Device response did not
match our challenge` = wrong email or password.

Then register each plug by MAC (lowercase, colon-separated — exactly as
shown in the step 5b options list):

```bash
scp claude_test/ha_add_tapo.sh unoq:/home/arduino/ha_add_tapo.sh
ssh unoq 'TAPO_USER=<email> TAPO_PASS=<password> \
  bash /home/arduino/ha_add_tapo.sh 18:69:45:71:05:2f'
ssh unoq 'TAPO_USER=<email> TAPO_PASS=<password> \
  bash /home/arduino/ha_add_tapo.sh 18:69:45:71:02:7c'
```

Expected: `RESULT: create_entry | title: <plug-name> P110M` for each.
The first registration walks pick_device → user_auth_confirm; HA then
stores the credentials, so the second plug usually skips the auth step
and creates its entry straight from pick_device.

Confirm the entities (each plug gets a main switch plus energy
monitoring — voltage, current, live/daily/monthly consumption):

```bash
ssh unoq 'curl -s http://localhost:8123/api/states \
  -H "Authorization: Bearer $(cat /home/arduino/.ha_token)" \
  | python3 -c "import sys,json
for e in json.load(sys.stdin):
    if \"tapo\" in e[\"entity_id\"]: print(e[\"entity_id\"], \"=\", e[\"state\"])"'
```

## 8. Control test: toggle a plug at 3-second intervals

End-to-end proof that HA can drive the relay. The script calls
`switch/turn_on` / `switch/turn_off` alternately, re-reads the entity
state after each command, and restores nothing at the end by design —
it finishes on `turn_off`, so pick a plug whose load can tolerate that.

CAUTION: check `sensor.<plug>_current_consumption` first and prefer a
plug with 0 W — toggling a plug cuts power to whatever is connected.
Note that the reading is only meaningful while the plug is ON: a plug
whose relay is off ALWAYS reports 0 W, even with a load attached, so
an off-state 0 W does not prove the socket is empty. Real example from
this rig: a plug that read 0.0 W while off drew 89.4 W during the
first ON window of the toggle test — a ~90 W device was connected the
whole time and got power-cycled. If the plug is off and you cannot
physically inspect the socket, turn it on once, wait a few seconds,
and read the sensor before deciding it is safe to toggle. Short ON
windows (3 s) may also be too brief for the connected device to
restart, so the later ON samples can misleadingly show ~0 W.

The script lives in this repo and reads the token on the board, so the
easiest way to run it is to stream it over SSH — no copy step needed:

```bash
ssh unoq 'bash -s -- switch.<plug_entity> 3' \
  < claude_test/toggle_test.sh
```

(Equivalent two-step form: `scp claude_test/toggle_test.sh
unoq:/home/arduino/` then `ssh unoq 'bash toggle_test.sh
switch.<plug_entity> 3'`.)

Expected (3 cycles = 6 transitions, ~3 s apart, relay clicks audibly):

```
initial state: off
11:47:37 cycle 1 turn_on -> state=on [OK]
11:47:40 cycle 1 turn_off -> state=off [OK]
...
final state: off
RESULT: 6 passed, 0 failed
```

Any `MISMATCH` line means HA accepted the service call but the plug did
not change state (network drop or stale entity) — check
`docker logs homeassistant --tail 50`.

## 9. Controlling the on-board MCU (STM32U585) from Home Assistant

The UNO Q is dual-brain: HA runs on the Linux side (QRB2210), while the
header pins and user LEDs belong to the STM32U585 MCU. They are wired
together by the `arduino-router` service (RPC over
`/run/arduino-router.sock`). This repo's `apps/ha-mcu-bridge/` App Lab
app exposes MCU pins to HA as MQTT switches and, independently of HA,
renders the Linux side's CPU/memory load as bars on the on-board
8x13 LED matrix (section 9e):

```
HA  <-MQTT->  Mosquitto  <-MQTT->  app python (paho-mqtt)
                                        |  Bridge.call("set_pin_by_name")
                                        v
                              arduino-router -> MCU sketch (RPC provide)
```

By default only the six on-board RGB LED channels (LED3/LED4 R,G,B —
active-low, nothing external wired) are exposed; header pins D2–D13 are
commented out in `python/main.py` `PIN_CONFIG` — enable only pins whose
wiring you know.

### 9a. Mosquitto broker (on the board)

```bash
ssh unoq 'mkdir -p /home/arduino/mosquitto'
scp apps/mosquitto/mosquitto.conf unoq:/home/arduino/mosquitto/
ssh unoq 'docker run -d --name mosquitto --restart=unless-stopped \
  --network=host -v /home/arduino/mosquitto:/mosquitto/config \
  eclipse-mosquitto:2'
```

The config listens on 127.0.0.1 (for HA, host network) AND 172.17.0.1
(docker0). The second listener matters: App Lab runs app python in a
BRIDGED compose container, where 127.0.0.1 is the container itself —
the app reaches the host at 172.17.0.1 instead. Nothing is exposed to
the LAN.

### 9b. Register the MQTT integration in HA

```bash
scp claude_test/ha_add_mqtt.sh unoq:/home/arduino/
ssh unoq 'bash /home/arduino/ha_add_mqtt.sh'
```

PASS = `step2` response is `create_entry` with `"state":"loaded"`.

### 9c. Deploy the bridge app (compiles + flashes the MCU)

```bash
scp -r apps/ha-mcu-bridge unoq:/home/arduino/ArduinoApps/
ssh unoq 'arduino-app-cli app start \
  /home/arduino/ArduinoApps/ha-mcu-bridge'
```

The first build compiles the zephyr core and flashes via on-board
OpenOCD (SWD bitbang) — allow a few minutes. Note: the MCU runs ONE
sketch at a time; starting this app replaces whatever app was flashed
before (`arduino-app-cli app stop <other-app>` first for a clean
switch). If you ever fall back to running app-cli over adb instead of
SSH, prefix it with `TMPDIR=/tmp`: adbd sets the Android-style
`TMPDIR=/data/local/tmp`, which does not exist on Debian and fails the
build with `Stat /Data/Local/Tmp: No Such File Or Directory`. Over SSH
this does not apply.

Check the python side connected:

```bash
ssh unoq 'docker logs ha-mcu-bridge-main-1 2>&1 | tail -3'
# expect: "MQTT connected: Success"
```

App Lab apps do NOT auto-start after a board reboot (HA and Mosquitto
do, via their Docker restart policies). Register the app as the
"default app" so the arduino-app-cli daemon starts it at boot:

```bash
ssh unoq 'arduino-app-cli properties set default \
  /home/arduino/ArduinoApps/ha-mcu-bridge'
# verify: arduino-app-cli properties get default
```

### 9d. Verify and drive the LEDs

```bash
# Discovery + state topics on the broker:
ssh unoq 'docker exec mosquitto mosquitto_sub -h 127.0.0.1 \
  -t "unoq/#" -C 3 -W 5 -v'
# expect: unoq/bridge/availability online, plus one JSON state
# document per LED, both "state":"OFF"

# Entities in HA (created automatically by MQTT Discovery):
# light.uno_q_mcu_led3  — RGB + brightness (PWM-backed)
# light.uno_q_mcu_led4  — RGB quantized to 8 colours (GPIO-only)

# End-to-end: LED3 at a colour and a mid brightness.
ssh unoq 'curl -s -X POST \
  http://localhost:8123/api/services/light/turn_on \
  -H "Authorization: Bearer $(cat /home/arduino/.ha_token)" \
  -H "Content-Type: application/json" \
  -d "{\"entity_id\":\"light.uno_q_mcu_led3\",
       \"rgb_color\":[255,0,180],\"brightness\":64}"'

# The bridge log prints the duty cycle it sent to the MCU, which is
# the quickest way to confirm the colour maths without watching the
# board:
ssh unoq 'arduino-app-cli app logs user:ha-mcu-bridge | tail -3'
# expect: led3 -> ON (64, 0, 45)
```

### 9e. Why LED3 dims and LED4 does not

Only LED3's three channels (PH10/11/12) are listed in the devicetree's
`pwm-pin-gpios`, mapped to pwm5 channels 1-3 at 500 Hz with inverted
polarity — the inversion cancels the active-low wiring, so
`analogWrite(255)` is full brightness and `analogWrite(0)` is off.
LED4 (PH13/14/15) has no PWM mapping, so it is driven with
`digitalWrite` and its colour is quantized to the eight on/off
combinations; lowering its brightness dims it by dropping channels
rather than smoothly.

### 9f. Getting the colour controls onto a dashboard

A freshly onboarded HA has an auto-generated `Overview`, which renders
each light as one Entities-card row — and that row shows **only a
toggle**. The colour wheel and brightness slider are one click deeper,
in the more-info dialog behind the entity name. Nothing is wrong with
the entity; it is easy to conclude HA can only switch the LED on and
off.

Rather than taking control of `Overview` (which permanently disables
auto-generation for every entity added later), add a separate
dashboard:

```bash
scp claude_test/ha_add_dashboard.py     apps/ha-dashboard/unoq-leds.yaml unoq:/home/arduino/
ssh unoq '/home/arduino/ha_venv/bin/python3     /home/arduino/ha_add_dashboard.py     --config /home/arduino/unoq-leds.yaml     --url-path uno-q --title "UNO Q"'
```

It appears in the sidebar as "UNO Q" (`/uno-q`) with a light card per
LED, an inline brightness slider for LED3, and one-tap buttons for
LED4's eight colours. Two gotchas: `url_path` must contain a hyphen or
HA rejects it, and `.storage/lovelace_dashboards` lags the live state
by a few seconds — verify with the `lovelace/dashboards/list`
WebSocket command, not the file.

The trap worth remembering: `analogWrite()` in this core only calls
`pwm_set_pulse_dt()` and never re-applies pinctrl. Once a pad has been
configured for GPIO — one `pinMode()` or `digitalWrite()` is enough —
the PWM signal stops reaching it until the MCU resets. That is why the
sketch keeps the LED3 channels out of its pin table entirely and
initialises them with `analogWrite(0)` instead of `pinMode`. If LED3
ever comes back as on/off-only, look for a stray GPIO call on those
pins first (`claude_test/led3_pwm_probe` reproduces both outcomes).

Verified result: 6/6 transitions OK, ~1 s command-to-state latency,
LED visibly blinking. The switches are also on the HA dashboard
(`http://<BOARD_IP>:8123`) under device "UNO Q MCU".

### 9e. System-load bars on the LED matrix

The same app samples the Linux side's CPU and memory usage with
`psutil` every 2 s (a daemon thread in `python/main.py`) and pushes
two integers to the sketch (`Bridge.call("show_load", cpu, mem)`),
which draws them on the 8x13 matrix:

```
row 0  .............   (margin)
row 1  ####.........   CPU bar   (2 rows, 0-13 cols ~ 0-100 %)
row 2  ####.........
row 3  .............   (blank separator)
row 4  #####........   MEM bar   (3 rows)
row 5  #####........
row 6  #####........
row 7  .............   (margin)
```

Implementation notes:

- `matrixBegin()` / `matrixWrite(const uint32_t[4])` are provided by
  the base firmware (declared `extern "C"` in the sketch, same as the
  official weather-forecast example) — no extra library in
  `sketch.yaml`.
- Raw frame bit order: pixel `i = row*13 + col` lives at
  `word[i/32]`, bit `i%32` (row 0 = top, col 0 = left). Determined by
  decoding the official example icons —
  `claude_test/decode_matrix_frame.py`.
- Any nonzero percentage lights at least one LED; 100 % = all 13.
- If the python side dies, the matrix freezes at the last frame; the
  sketch clears it on the next app start.

Verified: idle shows a 1-2 col CPU bar and a ~5 col MEM bar (~35 %);
a 20 s four-core stress (`for i in 1 2 3 4; do timeout 20 yes
> /dev/null & done`) visibly grows the CPU bar and it shrinks back
after, while the HA switch path keeps passing 6/6 (section 9d test).

### 9g. Automations: LED4 as a phone-WiFi indicator

The Home Assistant companion app publishes the phone's SSID as
`sensor.<device>_wi_fi_connection` (here
`sensor.sm_f966n_wi_fi_connection`), so an at-a-glance "am I on the
dorm network?" light needs no new integration -- only an automation
driving `light.uno_q_mcu_led4`.

**Check this first.** A configuration.yaml built by the onboarding
scripts in this repo contains only `default_config:` and the themes
include. The stock file that ships with a manual HA install also has

```yaml
automation: !include automations.yaml
```

and without that line HA loads **zero** automations no matter what the
UI editor or the config API writes -- both happily save into
`automations.yaml` and report success. Add it (backing the file up
first), create an empty `automations.yaml`, and `automation.reload`
picks it up without a restart:

```bash
ssh unoq 'cd /home/arduino/ha_config
cp configuration.yaml configuration.yaml.bak-$(date +%Y%m%d)
grep -q "^automation:" configuration.yaml ||
    printf "
automation: !include automations.yaml
" >> configuration.yaml
[ -f automations.yaml ] || echo "[]" > automations.yaml'
```

Then push the automation from the repo:

```bash
scp claude_test/ha_add_automation.py     apps/ha-automations/phone-wifi-led4.yaml unoq:/home/arduino/
ssh unoq '/home/arduino/ha_venv/bin/python3     /home/arduino/ha_add_automation.py     --config /home/arduino/phone-wifi-led4.yaml --id phone_wifi_led4'
# expect: loaded as automation.phone_wifi_state_on_led4 (on)
```

The installer re-reads the entity list after reloading and fails
loudly if the automation did not turn up, which is exactly what a
missing include looks like.

The automation itself colours LED4 by SSID:

| SSID | LED4 |
|---|---|
| `XiaomiDorm55` | blue |
| `TP-Link_0624` | green |
| anything else | red |

Red is the `default:` branch of the `choose`, so it also covers
`<not connected>`, `unavailable`, and `unknown` -- being away from
both known networks usually means no WiFi at all rather than a third
SSID, and "no known network" is exactly what the indicator should
show then. Adding a network is one more `choose` branch; the default
needs no touching.

It has three triggers, and the third is the non-obvious one:

- the SSID sensor changing state,
- `homeassistant.start`,
- `light.uno_q_mcu_led4` leaving `unavailable`.

The bridge's sketch turns both LEDs off in `setup()`, and the light
entity goes unavailable (MQTT LWT) whenever the App Lab app restarts,
so without the third trigger the LED sits dark until the phone next
changes networks. It also covers a race the second trigger cannot: MQTT
Discovery can re-create the light entity *after* `homeassistant.start`
fires, which is what happens on this board -- the LEDs reappeared ~20 s
into a restart here.

Testing it without moving the phone: overwrite the sensor state through
the REST API. The companion app pushes its real value back on the next
update, so the change is temporary.

```bash
ssh unoq 'TOKEN=$(cat /home/arduino/.ha_token)
curl -s -X POST http://localhost:8123/api/states/sensor.sm_f966n_wi_fi_connection   -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"   -d "{\"state\":\"XiaomiDorm55\"}"'
# expect in the bridge log: led4 -> ON (0, 0, 255)
```

### 9h. Automations: start the car when the phone leaves

The same SSID sensor drives a second automation
(`apps/ha-automations/away-car-aircon.yaml`): once the phone has been
off **every** known network for two minutes, turn
`switch.myhyundai_aircon` on so the cabin is already cooling.

```yaml
triggers:
  - trigger: template
    value_template: >-
      {{ states('sensor.sm_f966n_wi_fi_connection') not in
         ['XiaomiDorm55', 'TP-Link_0624', 'WUNIST_AAA',
          'unavailable', 'unknown'] }}
    for: "00:02:00"
```

Four things in those five lines are load-bearing:

- **Every place the user normally is belongs in the list.** The
  obvious version -- "not the home network" -- fires every time they
  arrive at work. Check the recorder for where the phone actually
  spends its day before choosing the list.
- **`unavailable` and `unknown` are in the list on purpose.** They
  mean the companion app stopped reporting (phone off, app killed, HA
  restarting), not that the phone went anywhere. A car must not start
  because Home Assistant lost contact with a phone.
- **`for:` is not padding.** Phones roam: the recorder here shows
  `<not connected>` at 12:27:31 and `TP-Link_0624` at 12:27:35, a
  four-second gap generated by the phone alone. Every such blip would
  otherwise start the car.
- **A template trigger re-arms only after going false**, so staying
  away does not re-fire it; the automation naturally runs once per
  departure.

The list is duplicated in `phone-wifi-led4.yaml`, which colours LED4
from the same sensor. YAML has no constants, and hiding it behind a
helper entity buys less than it costs — but the two files have to be
edited together.

**Testing an automation whose action is a real vehicle.** Do not fire
it and watch. Install `claude_test/away_trigger_probe.yaml` first: it
carries the identical `value_template` and `for:`, and writes a log
line through `system_log.write` instead of commanding anything. Drive
the SSID sensor over the REST API, then read the log:

```bash
# 30-second blip: must NOT fire
# sustained absence: must fire at T+120s exactly
grep "PROBE FIRED" /home/arduino/ha_config/home-assistant.log
```

Delete it afterwards
(`DELETE /api/config/automation/config/away_trigger_probe`) and
install the real one. The switch's own guards -- a 40 % vehicle
battery floor, a 10-minute auto-off, a 60-second cooldown -- then
cover the live path, so nothing extra is wrapped around the service
call.

One limitation worth knowing: the SSID only reaches HA while the phone
has *some* connectivity. A phone that loses WiFi and LTE together
stops pushing, the sensor keeps its last value, and the automation
never fires. It is an indicator of a reported network, not a presence
detector -- `device_tracker.sm_f966n` is the entity for that.

## 10. Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `ssh` refused on port 22 | Fresh image: sshd has no host keys. Re-run step 2a (needs the USB cable once). |
| `ssh` tries a strange port (e.g. 6800) | A global `Port` in the client's `/etc/ssh/ssh_config`. Pin `Port 22` in the per-host entry (step 2). |
| Board unreachable after router restart | DHCP gave it a new IP. Reserve a fixed lease in the router, or find it again via `adb shell ip addr show wlan0` over USB. |
| `adb devices` shows `no permissions` (bootstrap only) | See step 1. Re-plugging the board resets the no-sudo workaround. |
| Only 1 of 2 plugs found | The missing plug is off, still unpaired, or on another network (e.g. router guest SSID with client isolation — the Tapo app still shows it as online via cloud, which is misleading). Check the plug's LED, then re-run 5a. A plug that just joined shows up immediately in unicast probing. |
| No plugs found at all | Confirm the board and plugs share one subnet: compare `<BOARD_IP>` with the plug IPs shown in the Tapo app. Guest WiFi or a second router creates separate subnets. |
| `docker run` fails with disk errors | `df -h /` on the board; the HA image needs ~2 GB unpacked. Remove unused images: `docker image prune -a`. |
| Port 8123 not answering after 5 min | `ssh unoq 'docker logs homeassistant --tail 50'`. |
| HA API returns 401 | Access token expired (onboarding tokens last ~30 min). Run step 6 to mint a long-lived token. |
| tplink flow shows no devices | HA needs host networking (`--network=host`); verify the container was started exactly as in step 3. Also confirm 5a passes first. |
| Registration fails with `invalid_auth` | Wrong Tapo account email or password — KLAP is case-sensitive for both. Verify with the python-kasa one-liner in step 7 before retrying. A recently changed account password may not have propagated to the plug until it reconnects to the cloud. |
| Failed flow left half-open | Config flows expire on their own, but you can abort one immediately: `curl -X DELETE .../api/config/config_entries/flow/<flow_id>`. |
| Plug names don't match expectations | The HA entry title comes from the name set in the Tapo app (e.g. `tapo_p1`), which may not match your physical labels. Map name ↔ IP ↔ MAC with the step 7 entity listing before toggling anything. |
| App build fails: `Stat /Data/Local/Tmp` | Happens only when running app-cli over adb: adbd sets `TMPDIR=/data/local/tmp` (Android convention) which doesn't exist on the Debian board. Prefix with `TMPDIR=/tmp`, or just use SSH (step 9c). |
| Bridge app logs `ConnectionRefusedError` to MQTT | App Lab python runs in a bridged container — host loopback is unreachable. The broker must also listen on 172.17.0.1 (step 9a) and the app must connect there (default in `main.py`, override with `MQTT_HOST`). |
| MCU entities `unavailable` in HA | The bridge app is stopped (LWT set the availability topic to `offline`). `ssh unoq 'arduino-app-cli app restart /home/arduino/ArduinoApps/ha-mcu-bridge'`. |
| App python crashes `ModuleNotFoundError` after adding a dependency | `app restart` reuses the cached venv in `<app>/.cache/.venv` and does not react to `requirements.txt` changes. `app stop`, then `rm -rf <app>/.cache/.venv`, then `app start` to reprovision. |
| MCU entities `unavailable` after a board reboot | App Lab apps do not auto-start on boot. Register the app as the default app (step 9c) for automatic start, or run `arduino-app-cli app start <app-dir>` manually. |

## 11. File map

| File | Role |
|------|------|
| `claude_test/probe_all.py` | Subnet-wide unicast Tapo probe (step 5a) |
| `claude_test/ha_onboard.sh` | Scripted HA onboarding (step 4) |
| `claude_test/ha_flows.py` | List HA in-progress discovery flows over WebSocket (debug aid) |
| `claude_test/ha_login.sh` + `claude_test/mint_ll.py` | Re-login and mint a long-lived token (step 6) |
| `claude_test/ha_add_tapo.sh` | Register a Tapo device in HA by MAC (step 7) |
| `claude_test/toggle_test.sh` | Timed on/off toggle test with state verification (steps 8, 9d) |
| `claude_test/ha_add_mqtt.sh` | Register the MQTT integration in HA (step 9b) |
| `apps/mosquitto/mosquitto.conf` | Broker config, host-local listeners only (step 9a) |
| `apps/ha-mcu-bridge/` | App Lab app: MCU sketch (RPC pin control) + python MQTT bridge with HA Discovery (step 9c) |
| `docs/uno-q-vscode-wifi-guide.md` | Detailed SSH bootstrap + WiFi-only full-board development with VS Code (step 2) |
