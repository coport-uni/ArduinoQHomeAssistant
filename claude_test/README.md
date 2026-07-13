# claude_test/ — Debug & Verification Scripts

Index of one-off diagnostic scripts, per CLAUDE.md Section 3.

| File | Purpose | What was learned |
|------|---------|------------------|
| `probe_all.py` | Unicast python-kasa discovery probe across all 254 IPs of a /24 subnet (prefix as argv[1], default `192.168.1`). Run on the UNO Q inside a `python:3.12-alpine` container with `--network=host`. | Catches Tapo devices that ignore ICMP ping (ARP sweep alone is not sufficient). Both P110M(KR) plugs found: 192.168.1.79 (18:69:45:71:02:7C), 192.168.1.239 (18:69:45:71:05:2F). |
| `ha_onboard.sh` | Automates Home Assistant first-boot onboarding via REST API (create owner user, exchange auth code for token, finish core_config/analytics/integration steps). Configure via env vars `HA_USER`/`HA_PASS`/`HA_BASE`/`HA_TOKEN_FILE`; saves token to `~/.ha_token` on the board. | Full onboarding is scriptable without the UI; the auth code from `/api/onboarding/users` is exchanged at `/auth/token`. |
| `ha_flows.py` | Lists Home Assistant in-progress config flows over the WebSocket API (`config_entries/flow/progress`). Run inside the `homeassistant` container with `HA_TOKEN` env var. | Discovery flows (ssdp/zeroconf/dhcp/bluetooth) are only visible via WebSocket, not plain REST. |
| `ha_add_tapo.sh` | Adds a Tapo/Kasa device to HA by MAC via the tplink config flow (pick_device -> user_auth_confirm). Env: `TAPO_USER`, `TAPO_PASS`. Run on the board. | KLAP auth is case-sensitive for BOTH email and password. After the first successful entry, HA reuses stored credentials — the second device skips the auth step entirely. |
| `ha_login.sh` + `mint_ll.py` | Re-authenticates to HA (`/auth/login_flow`) and mints a 10-year long-lived token via the WebSocket API, stored in `~/.ha_token`. Env: `HA_PASS`. Run on the board. | Onboarding-issued access tokens expire in ~30 min; long-lived tokens must be minted over WebSocket (`auth/long_lived_access_token`), and the board's system python lacks aiohttp so minting must run inside the HA container. |
| `toggle_test.sh` | Toggles a HA switch entity on/off at 3 s intervals for N cycles, verifying reported state after each command. Usage: `toggle_test.sh <entity_id> <cycles>`. Run on the board — easiest over SSH without copying: `ssh unoq 'bash -s -- <entity_id> <cycles>' < claude_test/toggle_test.sh`. | `switch.tapo_p1` (052F, .239) passed 6/6 transitions twice (over adb 2026-07-13, over SSH 2026-07-14); state propagates to HA within ~1 s of the service call. |
| `ha_add_mqtt.sh` | Registers the MQTT integration in HA via config flow, pointing at the board-local Mosquitto (env: `MQTT_BROKER`, `MQTT_PORT`; defaults 127.0.0.1:1883). Run on the board. | The mqtt config flow's `broker` step accepts just `{broker, port}` and creates a loaded entry immediately — no restart needed. |
| `qtest_blink/` | Copy of the UNO Q app used to verify WiFi-only full-board programming: LED blink sketch (STM32U585) + Python heartbeat (Linux). Deployed on-board at `~/ArduinoApps/qtest_blink`, driven with `arduino-app-cli app start/restart/logs` over SSH. See `docs/uno-q-vscode-wifi-guide.md`. | The MCU is flashed from the board's own Linux side (OpenOCD, SWD bitbang), so WiFi+SSH suffices to program the whole board — no USB. First build+flash ~100 s; `app ps` panics in CLI v0.6.6 (use `app list`). Fresh images ship sshd with **no host keys** (`ssh-keygen -A` needed once). |

## Re-running the Tapo detection check

All commands run from the host over WiFi (`unoq` = SSH alias for the
board, see `docs/uno-q-vscode-wifi-guide.md`; ADB works too if USB is
connected).

```bash
# 1. Network-level check (from the board):
scp claude_test/probe_all.py unoq:/tmp/probe_all.py
ssh unoq 'docker run --rm --network=host -v /tmp/probe_all.py:/probe.py \
    python:3.12-alpine sh -c "pip install -q python-kasa && python /probe.py 192.168.1"'

# 2. Home Assistant-level check (tplink discovery, expect both P110M in options):
ssh unoq 'TOKEN=$(cat /home/arduino/.ha_token)
resp=$(curl -s -X POST http://localhost:8123/api/config/config_entries/flow \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"handler\":\"tplink\"}")
fid=$(echo "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin)[\"flow_id\"])")
curl -s -X POST http://localhost:8123/api/config/config_entries/flow/$fid \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{}"
curl -s -X DELETE http://localhost:8123/api/config/config_entries/flow/$fid \
  -H "Authorization: Bearer $TOKEN"'
```
