# Home Assistant on Arduino UNO Q — Setup, Tapo Integration & Control Guide

Reproducible procedure for provisioning any Arduino UNO Q board over ADB:
connect it to WiFi, install Home Assistant (HA) with Docker, detect
TP-Link Tapo P110M smart plugs, register them in HA (KLAP auth), and
verify end-to-end control with a timed on/off toggle test. Everything is
done from a host PC through `adb` — no monitor, keyboard, or SSH on the
board required.

Verified on: Arduino UNO Q (Debian 13 trixie, aarch64, kernel 6.16),
Docker 26.1.5 on the board, Home Assistant Container 2026.7.2,
2x Tapo P110M(KR) — detection, registration, and a 6/6-pass toggle test.

## 0. Prerequisites

- Host PC (Linux) with `adb` and Docker installed.
- Arduino UNO Q connected to the host via USB. The board boots Debian;
  the default Linux user is `arduino` and it is in the board's `docker`
  group (no sudo needed for Docker on the board).
- 2.4 GHz WiFi SSID + password for the board.
- Tapo P110M plugs already paired to the SAME WiFi network via the Tapo
  app, and powered on. (Pairing itself is done in the app; this guide
  only detects the plugs on the network.)
- ~2.5 GB free disk on the board (`df -h /`) for the HA image; ~1 GB RAM
  free while HA runs.

## 1. ADB connection

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

## 2. Connect the board to WiFi over ADB

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

## 3. Install Home Assistant with Docker

The UNO Q image ships with Docker preinstalled and the `arduino` user in
the `docker` group. Host networking is REQUIRED for HA device discovery
(DHCP/mDNS/SSDP/UDP broadcasts).

```bash
adb shell 'mkdir -p /home/arduino/homeassistant && \
  docker run -d --name homeassistant --restart=unless-stopped --privileged \
    -e TZ=Asia/Seoul \
    -v /home/arduino/homeassistant:/config \
    -v /run/dbus:/run/dbus:ro \
    --network=host \
    ghcr.io/home-assistant/home-assistant:stable'
```

The image pull takes several minutes on WiFi (~20 layers). Then:

```bash
adb shell "docker ps --format '{{.Names}} {{.Status}}'; \
  curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8123"
```

`HTTP 302` = HA is up and waiting for onboarding; `HTTP 200` = onboarding
already done. First boot takes 1–2 minutes after the container starts.

## 4. Onboarding (create the HA owner account)

Option A — browser: open `http://<BOARD_IP>:8123` and follow the wizard.

Option B — scripted (no browser), using `claude_test/ha_onboard.sh`:

```bash
adb push claude_test/ha_onboard.sh /home/arduino/ha_onboard.sh
adb shell 'HA_USER=arduino HA_PASS=<choose-a-password> \
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
adb push claude_test/probe_all.py /tmp/probe_all.py
adb shell 'docker run --rm --network=host \
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
adb shell 'TOKEN=$(cat /home/arduino/.ha_token)
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
adb push claude_test/mint_ll.py /tmp/mint_ll.py
adb push claude_test/ha_login.sh /home/arduino/ha_login.sh
adb shell 'HA_PASS=<HA-owner-password> bash /home/arduino/ha_login.sh'
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
adb shell 'docker run --rm --network=host python:3.12-alpine sh -c \
  "pip install -q python-kasa && \
   kasa --host <PLUG_IP> --username <email> --password <password> state"'
```

PASS = a `== <name> - P110M ==` state dump. `Device response did not
match our challenge` = wrong email or password.

Then register each plug by MAC (lowercase, colon-separated — exactly as
shown in the step 5b options list):

```bash
adb push claude_test/ha_add_tapo.sh /home/arduino/ha_add_tapo.sh
adb shell 'TAPO_USER=<email> TAPO_PASS=<password> \
  bash /home/arduino/ha_add_tapo.sh 18:69:45:71:05:2f'
adb shell 'TAPO_USER=<email> TAPO_PASS=<password> \
  bash /home/arduino/ha_add_tapo.sh 18:69:45:71:02:7c'
```

Expected: `RESULT: create_entry | title: <plug-name> P110M` for each.
The first registration walks pick_device → user_auth_confirm; HA then
stores the credentials, so the second plug usually skips the auth step
and creates its entry straight from pick_device.

Confirm the entities (each plug gets a main switch plus energy
monitoring — voltage, current, live/daily/monthly consumption):

```bash
adb shell 'curl -s http://localhost:8123/api/states \
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

```bash
adb push claude_test/toggle_test.sh /home/arduino/toggle_test.sh
adb shell 'bash /home/arduino/toggle_test.sh switch.<plug_entity> 3'
```

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
app exposes MCU pins to HA as MQTT switches:

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
adb shell 'mkdir -p /home/arduino/mosquitto'
adb push apps/mosquitto/mosquitto.conf /home/arduino/mosquitto/
adb shell 'docker run -d --name mosquitto --restart=unless-stopped \
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
adb push claude_test/ha_add_mqtt.sh /home/arduino/
adb shell 'bash /home/arduino/ha_add_mqtt.sh'
```

PASS = `step2` response is `create_entry` with `"state":"loaded"`.

### 9c. Deploy the bridge app (compiles + flashes the MCU)

```bash
adb push apps/ha-mcu-bridge /home/arduino/ArduinoApps/
adb shell 'TMPDIR=/tmp arduino-app-cli app start \
  /home/arduino/ArduinoApps/ha-mcu-bridge'
```

`TMPDIR=/tmp` is REQUIRED over adb: the board's adbd sets the
Android-style `TMPDIR=/data/local/tmp`, which does not exist on Debian
and fails the build with `Stat /Data/Local/Tmp: No Such File Or
Directory`. (Over SSH this is not needed.) The first build compiles the
zephyr core and flashes via on-board OpenOCD (SWD bitbang) — allow a
few minutes. Note: the MCU runs ONE sketch at a time; starting this app
replaces whatever app was flashed before (`arduino-app-cli app stop
<other-app>` first for a clean switch).

Check the python side connected:

```bash
adb shell 'docker logs ha-mcu-bridge-main-1 2>&1 | tail -3'
# expect: "MQTT connected: Success"
```

### 9d. Verify and toggle

```bash
# Discovery + state topics on the broker:
adb shell 'docker exec mosquitto mosquitto_sub -h 127.0.0.1 \
  -t "unoq/#" -C 7 -W 5 -v'
# expect: unoq/bridge/availability online, six .../state OFF

# Entities in HA (created automatically by MQTT Discovery):
# switch.uno_q_mcu_uno_q_led3_r ... led4_b  (6 total)

# End-to-end LED blink, 3 s cadence — LED3 blinks green on the board:
adb shell 'bash /home/arduino/toggle_test.sh \
  switch.uno_q_mcu_uno_q_led3_g 3'
```

Verified result: 6/6 transitions OK, ~1 s command-to-state latency,
LED visibly blinking. The switches are also on the HA dashboard
(`http://<BOARD_IP>:8123`) under device "UNO Q MCU".

## 10. Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `adb devices` shows `no permissions` | See step 1. Re-plugging the board resets the no-sudo workaround. |
| Only 1 of 2 plugs found | The missing plug is off, still unpaired, or on another network (e.g. router guest SSID with client isolation — the Tapo app still shows it as online via cloud, which is misleading). Check the plug's LED, then re-run 5a. A plug that just joined shows up immediately in unicast probing. |
| No plugs found at all | Confirm the board and plugs share one subnet: compare `<BOARD_IP>` with the plug IPs shown in the Tapo app. Guest WiFi or a second router creates separate subnets. |
| `docker run` fails with disk errors | `df -h /` on the board; the HA image needs ~2 GB unpacked. Remove unused images: `docker image prune -a`. |
| Port 8123 not answering after 5 min | `docker logs homeassistant --tail 50` on the board. |
| HA API returns 401 | Access token expired (onboarding tokens last ~30 min). Run step 6 to mint a long-lived token. |
| tplink flow shows no devices | HA needs host networking (`--network=host`); verify the container was started exactly as in step 3. Also confirm 5a passes first. |
| Registration fails with `invalid_auth` | Wrong Tapo account email or password — KLAP is case-sensitive for both. Verify with the python-kasa one-liner in step 7 before retrying. A recently changed account password may not have propagated to the plug until it reconnects to the cloud. |
| Failed flow left half-open | Config flows expire on their own, but you can abort one immediately: `curl -X DELETE .../api/config/config_entries/flow/<flow_id>`. |
| Plug names don't match expectations | The HA entry title comes from the name set in the Tapo app (e.g. `tapo_p1`), which may not match your physical labels. Map name ↔ IP ↔ MAC with the step 7 entity listing before toggling anything. |
| App build fails: `Stat /Data/Local/Tmp` | adbd sets `TMPDIR=/data/local/tmp` (Android convention) which doesn't exist on the Debian board. Prefix app-cli commands with `TMPDIR=/tmp` when working over adb (step 9c). |
| Bridge app logs `ConnectionRefusedError` to MQTT | App Lab python runs in a bridged container — host loopback is unreachable. The broker must also listen on 172.17.0.1 (step 9a) and the app must connect there (default in `main.py`, override with `MQTT_HOST`). |
| MCU entities `unavailable` in HA | The bridge app is stopped (LWT set the availability topic to `offline`). `TMPDIR=/tmp arduino-app-cli app restart /home/arduino/ArduinoApps/ha-mcu-bridge`. |

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
