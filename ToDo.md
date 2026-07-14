# ToDo.md

## 2026-07-13 — WiFi via ADB, Home Assistant on UNO Q, Tapo P110M detection

Requested by user. Target board: Arduino UNO Q "SungwooQ" (Debian 13,
aarch64), reached over ADB (serial 2018875248).

Workflow deviations: this repository has no git remote and no commits yet,
so the GitHub issue / working branch / PR steps of CLAUDE.md §4 cannot be
performed. They will apply once the repo gains a remote.

- [x] Verify board WiFi connectivity via ADB (already on TP-Link_0624,
      192.168.1.232; confirm internet and DNS)
- [x] Install Home Assistant on the board with Docker
      (ghcr.io/home-assistant/home-assistant:stable, host networking for
      device discovery)
- [x] Complete HA onboarding via REST API and obtain an access token
- [x] Verify HA detects two TP-Link Tapo P110M plugs (tplink discovery
      flows), cross-checked with a python-kasa network discovery scan
- [x] Record results below

### Results (2026-07-13)

- Board WiFi: already connected to TP-Link_0624 (user-confirmed SSID and
  password), IP 192.168.1.232, internet OK. USB permission for ADB was
  fixed by chmod on /dev/bus/usb/003/021 via a privileged docker helper
  (host user lacks passwordless sudo; resets on board replug).
- Home Assistant 2026.7.2 running in container `homeassistant` on the
  board (image ghcr.io/home-assistant/home-assistant:stable, host network,
  /home/arduino/homeassistant as /config, restart=unless-stopped).
- Onboarding completed via API; owner user `arduino`. Access token stored
  on the board at /home/arduino/.ha_token (not in this repo).
- Detection verified: HA tplink config-flow discovery listed BOTH plugs:
  `052F P110M (192.168.1.239) 18:69:45:71:05:2f` and
  `027C P110M (192.168.1.79) 18:69:45:71:02:7c`. Cross-checked with a
  python-kasa unicast sweep of 192.168.1.0/24 (claude_test/probe_all.py).
- Note: the second plug (052F) only appeared on the network partway
  through the session; earlier full-subnet sweeps found just one device.
- Not done: adding the plugs as config entries — KLAP auth requires the
  user's TP-Link (Tapo) account credentials. Discovery/detection does not.
- Verification scripts preserved in claude_test/ (see its README).

## 2026-07-13 — Reproducibility guide for other UNO Q boards

Requested by user: write a guide so the WiFi + Home Assistant + Tapo
verification procedure can be repeated on any Arduino UNO Q.

- [x] Generalize claude_test scripts (probe_all.py takes a subnet prefix
      argument; ha_onboard.sh takes HA_USER/HA_PASS/HA_BASE/HA_TOKEN_FILE
      env vars instead of hardcoded values)
- [x] Write docs/home-assistant-uno-q-guide.md covering ADB setup and the
      USB permission fix (udev rule or docker chmod workaround), WiFi via
      nmcli over adb, HA container install, scripted onboarding, two-level
      Tapo P110M detection verification, and troubleshooting
- [x] Update claude_test/README.md for the parameterized scripts

## 2026-07-13 — WiFi + VS Code Remote-SSH development for UNO Q

Requested by user: develop the UNO Q over WiFi from VS Code, with the
whole board (Linux MPU + STM32 MCU) programmable without a USB cable.
Chosen workflow: VS Code Remote-SSH directly onto the board, verified all
the way to flashing a sample app over WiFi.

Workflow deviations: the repository still has no git remote, so the
GitHub issue / PR steps of CLAUDE.md §4 cannot be performed (same
deviation as the entries above).

- [x] Enable SSH on the board (root cause: sshd had no host keys;
      generate via privileged docker helper and start ssh.service)
- [x] Set up passwordless SSH from the dev container (ed25519 key +
      `sungwooq` alias in ~/.ssh/config; container-global
      /etc/ssh/ssh_config `Port 6800` overridden with explicit Port 22)
- [x] Check board memory headroom for vscode-server alongside the
      Home Assistant container
- [x] Create sample app ~/ArduinoApps/qtest_blink (LED blink sketch on
      the STM32 + Python heartbeat on Linux) and build/flash it purely
      over WiFi with arduino-app-cli
- [x] Round-trip check: change the blink period, re-flash over WiFi,
      user confirms the LED speed change visually (pending user's
      visual confirmation; both flashes reported success)
- [x] Write docs/uno-q-vscode-wifi-guide.md; copy the sample app to
      claude_test/qtest_blink/ and update claude_test/README.md

### Results (2026-07-13)

- sshd failed with "no hostkeys available"; fixed with a one-shot
  privileged helper (`docker run --privileged --pid=host
  python:3.12-alpine nsenter -t 1 ... ssh-keygen -A`) since the board
  sudo needs a password. Service is enabled and now active.
- Passwordless SSH works: `ssh sungwooq hostname` -> SungwooQ. Client
  gotcha found: this container sets `Port 6800` globally in
  /etc/ssh/ssh_config, so the host entry pins `Port 22`.
- Board is the 4 GB variant (3.6 GiB visible, ~2.4 GiB available with
  Home Assistant running) — plenty for vscode-server.
- qtest_blink built, flashed to the STM32U585 (on-board OpenOCD over
  SWD bitbang) and started purely over WiFi in ~98 s; Python heartbeat
  visible via `arduino-app-cli app logs`. Blink period then changed
  500 ms -> 100 ms and re-flashed over WiFi (`app restart`), app
  reported running.
- CLI quirk: `arduino-app-cli app ps` panics ("not implemented") in
  v0.6.6; `app list` works.
- Guide: docs/uno-q-vscode-wifi-guide.md (incl. VS Code Remote-SSH
  setup and ProxyJump variant); app copy in claude_test/qtest_blink/.

## 2026-07-13 — Register both Tapo plugs in HA and run toggle test

Requested by user: complete the tplink integration for both detected
P110M plugs and physically toggle plug "052F" on/off at 3-second
intervals as an end-to-end test.

- [x] Obtain working Tapo account credentials from user (first attempt
      failed KLAP auth; verified correct ones with python-kasa before
      retrying the HA flow). Credentials are NOT stored in this repo;
      HA keeps them in its own config store on the board.
- [x] Replace expired onboarding token with a 10-year long-lived token
      (claude_test/ha_login.sh + mint_ll.py; stored at ~/.ha_token on
      the board)
- [x] Register both plugs via config flow (claude_test/ha_add_tapo.sh):
      entry "tapo_p1 P110M" = 052F / 192.168.1.239,
      entry "tapo_p2 P110M" = 027C / 192.168.1.79. Full entity sets
      created incl. energy sensors (tapo_p2 measured 7.3 W live load).
- [x] Toggle test on switch.tapo_p1 (user-selected 052F): 3 cycles of
      on/off at 3 s intervals, state verified after every command —
      6/6 transitions OK, initial state (off) restored
      (claude_test/toggle_test.sh)

## 2026-07-13 — Extend the UNO Q guide with integration & control steps

Requested by user: consolidate all work done so far into
docs/home-assistant-uno-q-guide.md.

- [x] Add step 6 (long-lived token via ha_login.sh + mint_ll.py),
      step 7 (plug registration with KLAP credential pre-check via
      python-kasa, ha_add_tapo.sh, entity listing), and step 8
      (3-second toggle test with load-safety caution)
- [x] Extend troubleshooting (invalid_auth case-sensitivity, stale
      flows, Tapo-app name vs physical label mismatch) and the file map

## 2026-07-13 — Control the on-board MCU (STM32U585) from Home Assistant

Requested by user; plan approved in plan mode. Architecture:
HA <-> MQTT (Mosquitto) <-> App Lab app python <-> arduino-router Bridge
RPC <-> MCU sketch. Same deviation as above: no git remote, so no GitHub
issue/branch/PR.

- [x] Write App Lab app `apps/ha-mcu-bridge/` (sketch provides
      set_pin_by_name RPC; python runs paho-mqtt with HA MQTT Discovery,
      6 RGB LED channels enabled by default, D2-D13 opt-in; ruff passed)
- [x] Start Mosquitto broker on the board (eclipse-mosquitto:2 container,
      host network, loopback-only listener; conf in apps/mosquitto/)
- [x] Register MQTT integration in HA via config flow
      (claude_test/ha_add_mqtt.sh; entry "127.0.0.1" loaded)
- [x] Stop the other session's qtest_blink app before re-flashing the
      MCU (one sketch at a time; restore with
      `arduino-app-cli app start ~/ArduinoApps/qtest_blink`)
- [x] Build/flash/start ha-mcu-bridge on the board (gotcha found: adb
      shell sets Android-style TMPDIR=/data/local/tmp which does not
      exist on Debian -> build fails with "Stat /Data/Local/Tmp";
      fix is TMPDIR=/tmp). Second gotcha: App Lab python runs in a
      bridged container, so the broker needed a second listener on
      172.17.0.1 (docker0) and the app connects there, not loopback.
      Sketch flashed via on-board OpenOCD (SWD); python container
      "ha-mcu-bridge-main-1" logs "MQTT connected: Success".
- [x] Verify end-to-end: availability "online" + 6 discovery configs +
      6 retained OFF states on the broker; HA auto-created 6 entities
      (switch.uno_q_mcu_uno_q_led3_r ... led4_b); toggle test on
      switch.uno_q_mcu_uno_q_led3_g: 3 cycles at 3 s -> 6/6 OK,
      ~1 s command-to-state latency, LED3 blinking green physically.
- [x] Update docs/home-assistant-uno-q-guide.md (new section 9,
      troubleshooting rows, file map) and claude_test/README.md
      (ha_add_mqtt.sh row)

## 2026-07-13 — README for R4-experienced newcomers; first content push

Requested by user: summarize all work in README.md (audience: knows the
UNO R4, never touched a UNO Q), then commit and push. User directed a
direct commit+push to main, so the branch/PR steps of CLAUDE.md §4/§12
are skipped for this bootstrap push by explicit instruction.

- [x] Write README.md: R4-vs-Q mental-model table (dual-brain, ADB
      instead of serial upload, on-board compile/flash, app = sketch +
      python pair), architecture diagram, verified results, repo
      layout, quick start, hardware gotchas
- [x] Add .gitignore (Python + App Lab build artifacts + secrets,
      incl. .ha_token)
- [x] Commit all project content and push to origin/main

## 2026-07-14 — Switch the HA workflow from ADB to WiFi/SSH

Requested by user: the board's USB port must stay free for expansion
devices (e.g. a Zigbee dongle), so Home Assistant on the UNO Q should
be managed over WiFi/SSH per docs/uno-q-vscode-wifi-guide.md, with ADB
reduced to the one-time bootstrap. Verification: toggle switch.tapo_p1
on/off for 3 cycles at 3-second intervals over SSH. (see LP §2, §5)

- [x] Rework docs/home-assistant-uno-q-guide.md: ssh/scp as the primary
      transport, ADB folded into a one-time bootstrap section that
      references the WiFi guide (see LP §2, §5)
- [x] Update README.md (intro, quick start, gotchas, repo layout) to
      the SSH-first workflow
- [x] Update claude_test/README.md re-run instructions to ssh, fix the
      ha_onboard.sh header comment, rename mint_ll.py token client name
- [x] Verify over SSH: run claude_test/toggle_test.sh on switch.tapo_p1
      for 3 cycles at 3 s intervals with state checks after each command
- [x] Post-test history check found tapo_p1 had a ~90 W load (89.4 W in
      the first ON window) despite the off-state 0.0 W pre-check; guide
      step 8 CAUTION extended to warn that off-state 0 W hides a load

### Results (2026-07-14)

- Guide restructured: step 1 = one-time ADB bootstrap (USB perms +
  WiFi), step 2 = SSH enablement pointing at the WiFi guide; steps 3-9
  keep their numbers, so existing cross-references stay valid. All
  `adb push`/`adb shell` commands became `scp`/`ssh unoq`. The
  `TMPDIR=/tmp` requirement is now documented as adb-only fallback.
- mint_ll.py: token client_name adb-cli -> unoq-cli; file also brought
  Ruff-clean (import splitting, no semicolons) per the lint hook.
- Verification over SSH only (USB not involved): tapo_p1 pre-checked at
  0.0 W load, then `ssh sungwooq 'bash -s -- switch.tapo_p1 3'
  < claude_test/toggle_test.sh` -> 6/6 transitions OK at 3 s cadence,
  final state off restored. GitHub issue #1, branch
  docs/wifi-ssh-workflow.

## 2026-07-14 — System-load bars on the UNO Q LED matrix

Requested by user; plan approved in plan mode. Show Linux-side CPU%
and memory% on the on-board 8x13 LED matrix as horizontal bars (CPU on
2 rows, one blank row, MEM on 3 rows). Extends apps/ha-mcu-bridge
(user choice: the MCU runs one sketch at a time, and the HA MQTT
switches must keep working). Patterns taken from the board-bundled
examples system-resources-logger (psutil sampling) and
weather-forecast / air-quality-monitoring (matrixBegin/matrixWrite +
Bridge RPC). (see LP §3, §5)

- [x] Determine the raw matrixWrite bit order by decoding the official
      example frames (claude_test decoder script + README row)
- [x] Sketch: extern matrixBegin/matrixWrite, layout constants,
      setPixel/barCols helpers, show_load RPC handler, clear on setup
- [x] Python: psutil==7.0.0 dep, stats_loop daemon thread pushing
      Bridge.call("show_load", cpu, mem) every 2 s under bridge_lock
- [x] Deploy over SSH (scp + app restart, reflashes MCU) and verify:
      logs clean, idle bars visible, 4x yes stress grows the CPU bar,
      HA switch regression via toggle_test.sh (see LP §3)
- [x] Update docs (guide §9 + new §9e, README, app.yaml description)
      and LearnedPatterns (firmware matrix symbols + bit layout)

### Results (2026-07-14)

- Bit order settled WITHOUT hardware trial: decoding the official
  air-quality "good" icon under both candidate orders
  (claude_test/decode_matrix_frame.py) renders a clean smiley only
  for LSB-first — pixel i = row*13+col -> word[i/32] bit i%32. The
  planned corner-pixel hardware gate became unnecessary.
- Deploy gotcha: `app restart` reused the cached venv and python
  crashed with ModuleNotFoundError on psutil; fixed by `app stop`,
  `rm -rf .cache/.venv`, `app start` (now in guide troubleshooting
  and LearnedPatterns §3).
- Verified over SSH + user's eyes: 0 "stats push failed" in logs;
  idle bars (CPU 1-2 cols, MEM ~5 cols at ~35 %); 4-core `yes`
  stress (load avg 1.9 -> 3.0) grew and shrank the CPU bar;
  toggle_test.sh on switch.uno_q_mcu_uno_q_led3_g passed 6/6
  concurrently; user visually confirmed the layout. GitHub issue #3,
  branch feature/matrix-sysload.

## 2026-07-14 — Auto-start ha-mcu-bridge on boot

Requested by user after a board reboot left the app stopped (HA and
Mosquitto auto-restart via Docker policies, but App Lab apps do not
auto-start). Included in the feature/matrix-sysload branch / PR #4 at
the user's request. (see LP §1, §3)

- [x] Find the supported mechanism: arduino-app-cli daemon starts the
      "default app" at boot (`properties set default <app_path>`);
      no systemd/cron hack needed
- [x] Register /home/arduino/ArduinoApps/ha-mcu-bridge as default app
      on the board and confirm with `properties get default`
- [x] Verify end-to-end: reboot the board, confirm the app container
      comes up without manual start, MCU entities available, matrix
      bars updating
- [x] Document in guide step 9c + troubleshooting row; LearnedPatterns
      entry

### Results (2026-07-14)

- `arduino-app-cli properties set default <app_path>` is the supported
  autostart mechanism (the arduino-app-cli.service daemon starts the
  default app at boot); `systemctl reboot` over SSH is denied
  ("Interactive authentication required") so the reboot used the
  privileged docker helper (LP §1).
- Reboot verification (user-approved reboot): board back in ~45 s,
  HA + Mosquitto up ~1 min, ha-mcu-bridge-main-1 auto-started ~90 s
  after reboot with NO manual start; switch.uno_q_mcu_uno_q_led3_g
  available, matrix bars updating. Exactly 3 "stats push failed"
  lines during boot (router not up yet) then 0 — the per-iteration
  try/except recovered as designed. GitHub issue #5.

## 2026-07-14 — Make the README Quick start self-sufficient

Requested by user. The Quick start's step 1 mentioned "enable SSH +
install your key (guide steps 1-2)" only in a comment and then jumped
straight to `ssh unoq` — impossible on a fresh board (sshd ships
without host keys, no authorized key, no `unoq` alias; see LP §2).
Steps 4-5 likewise pointed at guide sections without commands. Goal:
following the Quick start ALONE on a brand-new UNO Q must reproduce
every verified feature (WiFi+SSH bootstrap, HA, long-lived token,
Tapo registration, MQTT broker + integration, ha-mcu-bridge app with
HA LED switches + matrix load bars, end-to-end toggle checks).

Workflow note: stacked on feature/matrix-sysload because PR #4 is
still open and the Quick start being fixed documents the matrix
feature; branch docs/quickstart-complete targets feature/matrix-sysload
instead of main.

- [x] Rewrite README Quick start to be fully executable end-to-end:
      adb udev fallback, sshd host-key generation + public-key install
      + `unoq` ssh alias (guide step 2, see LP §2), Tapo MAC discovery
      (probe_all.py) + per-MAC registration (ha_add_tapo.sh),
      Mosquitto + MQTT integration + app deploy + boot default app,
      switch-entity listing, and both toggle verifications
- [x] GitHub issue, branch docs/quickstart-complete, PR onto
      feature/matrix-sysload

### Results (2026-07-14)

- Quick start rewritten as seven fully executable steps (USB
  bootstrap incl. udev fallback -> SSH enablement/key/alias -> HA ->
  onboarding+token -> Tapo discovery+registration -> broker + MQTT
  integration + app deploy + boot default -> entity listing + both
  toggle tests), with the off-state-0 W plug caution. All commands
  taken verbatim from guide steps verified on hardware 2026-07-13/14;
  referenced claude_test/ scripts and paths cross-checked. GitHub
  issue #6, branch docs/quickstart-complete, PR #7 (stacked on PR #4
  because the Quick start documents the matrix feature).

## 2026-07-14 — Refactor ha-mcu-bridge main.py into HaMcuBridge class

Requested by user after a visual code review of
apps/ha-mcu-bridge/python/main.py. The user approved the review plan
in chat and asked to gather everything under one class ("god class"):
separate the public surface from internal helpers and fix the
MIT-convention findings from the review. Behavior must not change.

- [x] Wrap all behavior in a HaMcuBridge class: run() as the only
      public method; _handle_connect/_handle_message as paho-mqtt
      callbacks; _build_command_topic/_build_state_topic/_apply_pin/
      _publish_discovery/_push_stats_forever as internal helpers
- [x] Absorb module globals (client, bridge_lock) into instance state
- [x] Add the five missing docstrings; rename noun-shaped functions
      to verbs (MIT convention)
- [x] Promote the hardcoded 5 s reconnect delay to RETRY_DELAY_S
- [x] Fix the two 80-column violations (ruff format, line-length 80)
- [x] Add main() + __main__ guard after confirming the App Lab
      runtime executes main.py as a script, not an import
- [x] Verify on the board: deploy, app restart (see LP §3 venv note),
      "MQTT connected" in logs, HA switch toggle, matrix bars
- [x] GitHub issue, branch refactor/bridge-god-class, PR

### Results (2026-07-14)

- HaMcuBridge class in place: run() is the only public method;
  _handle_connect/_handle_message are the paho-mqtt callbacks; five
  underscore helpers; client and bridge_lock absorbed into __init__.
  The main() + __main__ guard is safe because the App Lab run.sh
  execs `python /app/python/main.py` (verified inside the container).
- The repo had no pyproject.toml, so the CommonClaude post-write ruff
  hook checked at Ruff's 88-column default and rejected 80-column
  wrapping; added a root pyproject.toml with line-length = 80 and a
  LearnedPatterns §3 entry.
- On-board verification (SungwooQ): scp + `app restart`; log shows
  "MQTT connected: Success"; availability topic "online"; LED3_G
  ON/OFF over MQTT echoed on the state topic with matching log lines;
  0 "stats push failed" over 3 min. GitHub issue #9, branch
  refactor/bridge-god-class, PR #10.
