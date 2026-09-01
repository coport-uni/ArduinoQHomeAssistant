# MyHyundai Aircon — Home Assistant Custom Component Guide

Remote climate control for a Korean Hyundai vehicle from Home
Assistant, implemented per
[SPEC-myhyundai-aircon-component.md](SPEC-myhyundai-aircon-component.md).

> **Read this first.** This is an *unofficial* automation. It works
> by tapping the MyHyundai (마이현대, `com.hyundai.oneapp.kr`) home
> screen widget on a dedicated Android phone over ADB — because no
> official control API exists for the Korean region. A MyHyundai app
> update can break it at any time. Review your account's terms of
> service yourself, and keep this strictly personal-use: every
> deployment runs on the owner's own phone and account.

Verified end-to-end on 2026-09-01: a real Casper Electric received
aircon ON in ~32 s and OFF in ~10 s from `switch.myhyundai_aircon`,
with results judged from the app's push notifications.

## 1. How it works

```
Home Assistant (custom component)
  │  adb-shell over TCP :5555, RSA key auth
  ▼
Dedicated Android phone (Galaxy Z Fold3, cover screen)
  │  wake → HOME → tap the MyHyundai widget button
  ▼
MyHyundai app → Bluelink server → vehicle
  │
  ▼
Result push notification ("원격제어 결과 안내")
  ← polled via `dumpsys notification --noredact` and judged
```

The switch is **assumed-state** (`assumed_state: true`): the
component cannot read the real climate state, so ON reflects the
last judged success and auto-reverts after the vehicle-side maximum
runtime (10 min by default).

The tap sequences are **data, not code**: they live in
`custom_components/myhyundai_aircon/recipes/default.json`. When the
app UI changes, edit the JSON and call the
`myhyundai_aircon.reload_recipe` service — no Python changes, no
restart.

## 2. Phone preparation (spec §12)

Settings on the dedicated phone. Items marked **required** were
proven necessary on real hardware; the rest reduce flakiness.

| Area | Setting | Value | Note |
|---|---|---|---|
| Developer options | USB debugging (USB 디버깅) | On | **Required.** Also accept the RSA prompt ("항상 허용") |
| Developer options | Stay awake while charging (충전 중 화면 켜짐 유지) | On | recommended |
| Developer options | Animation scales ×3 (애니메이션 배율) | 0.5x | recommended |
| Screen | Screen timeout (화면 자동 꺼짐) | Maximum | the component wakes the screen itself |
| Screen | **Lock screen (잠금 화면)** | **None (없음)** | **Required.** A PIN/pattern blocks automation cold — verified during bring-up |
| Screen | Rotation | Portrait, locked | |
| Foldable | Fold state | Folded, cover screen | the widget renders fine on the cover screen (verified) |
| Launcher | MyHyundai widget | On the **default** home page | HOME must land on it (verified: page 1 of 2, default) |
| Battery | MyHyundai battery optimization | Excluded | keeps pushes prompt |
| Battery | Charge limit | 85 % if supported | phone lives on the charger |
| Network | Phone IP | DHCP reservation | this rig: 192.168.31.113 |
| System / apps | Auto-updates (system and MyHyundai) | Off | an app update can change the UI |

**ADB over TCP**: run `adb tcpip 5555` once per phone boot. On this
rig the phone hangs off the UNO Q's USB hub, so the board itself
can re-arm TCP after a phone reboot (adb client extracted at
`/home/arduino/adb-local/`, see §7). Keep the phone on the charger
and avoid reboots.

## 3. Installation (this rig: HA Core venv on the UNO Q)

The board runs HA Core 2026.2.3 in a venv
(`home-assistant.service`, config at `/home/arduino/ha_config`).
Deploy from the repo checkout:

```bash
scp -r custom_components/myhyundai_aircon \
  unoq:/home/arduino/ha_config/custom_components/
ssh unoq 'sudo systemctl restart home-assistant'
```

HA installs the pinned `adb-shell[async]==0.4.4` (the same version
HA core's androidtv integration pins — do not change one without
the other) automatically on first load.

For a HACS-based install instead, add this repository as a custom
repository of type "Integration" (`hacs.json` is present).

## 4. Configuration

Settings → Devices & Services → Add Integration → **MyHyundai
Aircon**:

| Field | Value |
|---|---|
| Device IP address | the phone's reserved IP (e.g. 192.168.31.113) |
| ADB TCP port | 5555 |
| ADB key path | empty to auto-generate under `.storage/` — the phone will then show one RSA prompt to accept. Point it at an already-authorized key (e.g. `/home/arduino/.android/adbkey`) to skip the prompt |
| Entity name prefix | `myhyundai` |

The flow proves the connection, uses the phone serial as the unique
ID, and stores the effective screen resolution automatically
(Override size preferred — screenshots and UI dumps use it; on the
Z Fold3 cover screen that is 840x2289, not the physical 832x2268).

**Options** (gear icon on the integration) expose the spec §5.2
tuning: cooldown (default 60 s — do **not** lower it; it protects
the vehicle's 12 V battery from rapid repeat commands), minimum
command gap, vehicle battery sensor + floor, auto-off minutes,
sequence timeout, retries, screen check, dump-on-failure. The
notification wait limit is set per-step in the recipe instead.

## 5. Entities and services

| Entity | Meaning |
|---|---|
| `switch.myhyundai_aircon` | Aircon ON/OFF (optimistic; auto-OFF after `aircon_max_minutes`). Attributes: `last_result`, `last_error_code`, `last_started`, `expires_at`, `screen_checked` |
| `sensor.myhyundai_last_result` | `success` / `failure` / `unknown` |
| `sensor.myhyundai_last_error` | last spec §9.3 error code or `none` |
| `sensor.myhyundai_last_notification` | last judged notification text |
| `binary_sensor.myhyundai_device_connected` | ADB reachability (30 s poll, 5/15/45/60 s reconnect backoff) |
| `sensor.myhyundai_vehicle_battery` | EV battery %, scraped read-only from the widget |
| `sensor.myhyundai_vehicle_range` | Driving range (km), scraped from the widget |
| `binary_sensor.myhyundai_doors_locked` | 문잠김/문열림 from the widget status text; unknown until observed |
| `sensor.myhyundai_data_updated_at` | The widget's "N시 기준" timestamp (Korean 오전/오후 parsed; day rolls back when needed — requires the HA timezone to be set correctly) |
| `sensor.myhyundai_app_version` | MyHyundai versionName from `dumpsys package` — automate an alert on change to catch UI-breaking updates early |

The vehicle sensors come from a **read-only widget scrape** (wake →
home → UI dump → parse) every `vehicle_poll_minutes` (default 15,
0 disables), serialized behind the sequence lock and never sending
a vehicle command. A failed scrape keeps the previous values. The
widget's refresh control is deliberately never tapped — it may ping
the vehicle.

| Service | Purpose |
|---|---|
| `myhyundai_aircon.capture_dump` | Save the phone's UI hierarchy XML + screenshot PNG to `config/myhyundai_aircon_dumps/` (retention: 40 files). The tool for recipe work and debugging |
| `myhyundai_aircon.run_sequence` | Run any recipe sequence through the same guards/retries as the switch; `ignore_guards: true` bypasses the guards |
| `myhyundai_aircon.reload_recipe` | Re-read the recipe JSON without restarting HA |

Every run fires a `myhyundai_aircon_result` event (`sequence`,
`result`, `code`, `elapsed_sec`, `attempt`, `screen_checked`,
`notification_text`) for automations.

Note: because of the cooldown guard, turning the switch OFF within
60 s of turning it ON is rejected with `E_COOLDOWN` — wait, or call
`run_sequence` with `ignore_guards: true` if you must.

## 6. Error codes (spec §9.3)

| Code | Meaning | Retried? |
|---|---|---|
| `E_RECIPE_INCOMPLETE` | placeholders / empty steps in the sequence | no |
| `E_MIN_GAP` / `E_COOLDOWN` | guard rejection (too soon) | no |
| `E_BATTERY_LOW` | vehicle battery sensor under the floor | no |
| `E_DEVICE_OFFLINE` | ADB unreachable | via coordinator backoff |
| `E_SCREEN_MISMATCH` | resolution differs from baseline — phone probably unfolded | no |
| `E_SESSION_EXPIRED` | login screen detected (needs `login_markers`, see §8) | no |
| `E_UNKNOWN_SCREEN` | expected UI node not found | no (dump saved) |
| `E_TIMEOUT` | no result notification in time | yes — force-stops the app first |
| `E_VEHICLE_FAIL` | failure notification received | yes — after `retry_gap_sec` |

With `dump_on_failure` on (default), every failed attempt saves an
XML+PNG pair named `fail-<sequence>-<attempt>`.

## 7. This rig's specifics (UNO Q)

- Phone: Galaxy Z Fold3 (SM-F926N, Android 15), serial
  R3CR80H1GBN, on the board's USB hub for power + one-time ADB
  bootstrap, WiFi IP 192.168.31.113.
- A standalone adb client lives at `/home/arduino/adb-local/`
  (extracted from .debs — Debian's adb package conflicts with the
  board's preinstalled Arduino android libraries). Run it with
  `LD_LIBRARY_PATH=/home/arduino/adb-local/rootfs/usr/lib/aarch64-linux-gnu/android`
  and binary
  `.../rootfs/usr/lib/android-sdk/platform-tools/adb`; the
  `arduino` user is in `plugdev` for USB access.
- After a phone reboot: from the board, `adb tcpip 5555` over the
  USB connection re-arms TCP mode.
- The component's config entry reuses the already-authorized
  `/home/arduino/.android/adbkey`, so no extra phone prompts.

## 8. Recipe maintenance

`recipes/default.json` currently encodes (all values read from the
real device, never guessed):

- `aircon_on` / `aircon_off`: wake → HOME → wait for the launcher →
  wait for + tap the widget button matched by
  `content_desc: "공조 켜기" / "공조 끄기"` (the widget exposes no
  resource-ids) → await the result notification
  (`공조가 켜졌습니다` / `공조가 꺼졌습니다`, 60 s). No confirm
  popup exists.
- Two values are still unobserved and can be filled later by
  editing the JSON only:
  - **Failure texts (U6)**: when a run ever fails for real (doors
    open, 96-hour window expired…), read the exact text from
    `sensor.myhyundai_last_notification` or a `capture_dump`, add
    it to `failure_contains`, and `reload_recipe`. Until then a
    failure judges as `E_TIMEOUT` and retries.
  - **Login markers (U8)**: if the app ever logs out, run
    `capture_dump` on the login screen and put a distinctive
    string into `login_markers` so runs fail fast with
    `E_SESSION_EXPIRED` instead of timing out.
- Widget button reference (from the 2026-09-01 dump):
  `공조 켜기`, `공조 끄기`, `문 잠금`, `충전 시작` — door lock and
  charging sequences can be added the same way.

## 9. Operational caveats (spec §15)

1. Hyundai remote control only works within **96 hours of the last
   ignition-off**; after that expect `E_VEHICLE_FAIL`/`E_TIMEOUT`.
2. Remote climate runs at most **10 minutes** vehicle-side; the
   auto-off default matches.
3. Keep the 60 s cooldown — repeated remote commands stress the
   vehicle's 12 V battery.
4. Unofficial automation: app updates can break it (that is what
   `capture_dump` + the recipe JSON are for), and account terms are
   the owner's responsibility.
5. Personal use only.
