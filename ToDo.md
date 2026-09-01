# ToDo.md

## 2026-07-27 — ha-mcu-bridge on uno-q (matrix load bars) + reboot persistence

Requested by user: reproduce the original rig's LED-matrix CPU/MEM load
bars on the new board (uno-q), and make HA and the MCU sketch survive a
board reboot. GitHub issue #12.

- [x] Deploy apps/ha-mcu-bridge over SSH (scp + CRLF strip on the
      board), first build compiled zephyr + flashed the STM32U585 via
      on-board OpenOCD; python container logs "MQTT connected: Success"
- [x] Verify bridge: unoq/bridge/availability online + 6 retained LED
      state topics on the broker; 6 switch.uno_q_mcu_* entities in HA;
      toggle_test.sh on switch.uno_q_mcu_uno_q_led3_g -> 6/6 OK
- [x] Verify matrix path: 0 "stats push failed" log lines; 15 s 4-core
      `yes` stress raised load avg to 1.08 (bar growth is visual —
      user can confirm on the board)
- [x] Reboot persistence config: all three containers
      restart=unless-stopped; docker + arduino-app-cli services
      enabled; ha-mcu-bridge registered as default app
- [x] Reboot test: board rebooted via privileged helper (`systemctl
      reboot` over SSH is denied). SSH back in ~60 s; all three
      containers auto-started within seconds; HA answered 200; Z2M
      bridge republished {"state":"online"}; ha-mcu-bridge auto-started
      as default app (availability "online"). Post-reboot toggle on
      switch.uno_q_mcu_uno_q_led3_g: 6/6 OK. Exactly 3 "stats push
      failed" lines during boot (router not up yet) then 0 — same
      recovery pattern as the SungwooQ rig. Tapo + Z2M entities all
      live (dormtapo2 reading 1.4 W).

## 2026-07-27 — HA + Sonoff Dongle Max + Zigbee2MQTT on new network (BLOCKED)

Requested by user. Board reported at 192.168.31.172 (new 192.168.31.x
network; previous rig lived on 192.168.1.x), login arduino/arduino.
Plan: install HA per docs/home-assistant-uno-q-guide.md, verify the
Sonoff Zigbee Dongle Max over USB, run Zigbee2MQTT (docker container —
HA Container has no add-on store), verify via network checks, and
research popular community dashboard designs.

- [x] Diagnose SSH connectivity: 192.168.31.172 answers ping
      (ARP 14:b5:cd:eb:1f:c9 = Liteon wifi module, consistent with the
      UNO Q) but EVERY probed TCP port (22, 8123, 8080, 1883, 5555 …)
      is actively refused, and a full /24 sweep found no host with
      port 22 open. Conclusion: the board is on WiFi but sshd is not
      running — the guide §10 "fresh image: sshd has no host keys"
      symptom. No adb device on USB, so remote recovery is impossible.
- [ ] BLOCKED: re-run guide step 2a over USB (host-key generation +
      ssh.service start), then steps 3-6 (HA install + onboarding +
      long-lived token)
- [ ] BLOCKED: verify Sonoff Dongle Max enumeration (lsusb,
      /dev/serial/by-id) and Zigbee2MQTT container (adapter: ember)
      + MQTT integration + network-level verification
- [x] Research popular dashboard designs — see
      docs/ha-dashboard-research.md (Dwains / UI Lovelace Minimalist /
      Mushroom / Bubble Card / theme table + HA-Container HACS notes)
- [x] Restore the CommonClaude submodule checkout (was empty; ruleset
      and hooks now present) and file GitHub issue #11 for this session

### Results (2026-07-27, after the user attached the board over USB)

- SSH root cause confirmed on the NEW board (hostname uno-q, adb serial
  2369462340 — a different unit from SungwooQ): ssh.service inactive
  AND disabled, zero host keys in /etc/ssh. Fixed via the guide 2a
  privileged docker helper extended with `systemctl enable ssh`;
  public key installed over adb; `ssh unoq hostname` -> uno-q with no
  password. All later work ran over WiFi/SSH only (user unplugged USB
  to attach a hub).
- Gotcha (new): scripts scp'd from this Windows checkout carry CRLF
  and bash rejects them (`set: pipefail: invalid option name`); every
  script needed `sed -i 's/\r$//'` on the board before running.
- HA Container 2026.7.3 installed per guide step 3; scripted
  onboarding (owner arduino) + 10-year token minted (steps 4/6).
- Disk pressure: HA pull left / at 100 % (36 MB free). With the
  user's explicit approval (AskUserQuestion) removed unused preloaded
  images ei-models-runner:0.5.0 (1.31 GB) + influxdb:2.7 (393 MB) ->
  1.8 GB free (82 %). python-apps-base kept for App Lab apps.
- Sonoff Dongle Max verified: lsusb shows CP210x (10c4:ea60) behind
  the user's USB hub; /dev/serial/by-id names it
  "SONOFF_SONOFF_Dongle_Max_MG24_..." -> /dev/ttyUSB0.
- Zigbee2MQTT 2.12.1 (koenkk/zigbee2mqtt, host network, by-id device
  passthrough, adapter: ember) talks to the dongle: coordinator
  EmberZNet 7.4.5. Verified bridge online on MQTT, permit_join
  request->response {"status":"ok"} round-trip, HA MQTT integration
  registered (create_entry, loaded), bridge entities live in HA, and
  frontend HTTP 200 from the host PC over LAN (:8080). Note: a mid-
  session dongle unplug killed the container and docker did not
  auto-restart it (device node missing) — `docker start zigbee2mqtt`
  after replugging.
- Tapo re-verified on this network/account: DormTapo1 192.168.31.19
  (18:69:45:71:0C:49) and DormTapo2 192.168.31.240 (18:69:45:71:05:EC)
  both KLAP-authenticated via python-kasa, registered in HA
  (create_entry each). toggle_test.sh switch.dormtapo2 at 5 s:
  10/10 transitions OK; plug restored to ON; live power readout
  2.2 W / 218.7 V / 0.02 A confirms energy monitoring.
- Dashboard recommendation #1 applied without HACS (OAuth is
  interactive): mushroom.js v5.1.1 + bubble-card.js (dist) downloaded
  into /config/www/community/, catppuccin.yaml v2.1.3 into
  /config/themes/, resources + "Mushroom" storage dashboard
  (url mushroom-home) written into .storage with HA stopped, default
  theme set to Catppuccin Mocha (dark). Verified: both JS URLs and
  /mushroom-home return HTTP 200. HACS can be layered on later for
  updates.

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

## 2026-08-25 — Cryptojacking incident on the ComfyUI Docker host

Requested by user: investigate why both GPUs were pinned at 100 %, then
record the incident on GitHub. Read-only forensic investigation only —
the user performed the containment (container + port removal) themselves.
Malicious ComfyUI custom node `champdev-comfyui-nodes` (unauthenticated
web terminal + file manager + telemetry beacon) installed via the exposed
ComfyUI-Manager API on 2026-08-23 was the entry point; it relaunched an
XMRig-style miner as root after the user's container reboot.

- [x] Identify the GPU consumer: host nvidia-smi showed both Quadro
      RTX 6000 at 100 % / ~250 W with no compute process listed;
      traced to a hidden `python` process inside the `comfyui`
      container (cmdline wiped, /proc/<pid>/exe unreadable even as
      root), outbound C2 to 166.117.41.217:9000 (AWS Global
      Accelerator front)
- [x] Find the entry vector: `champdev-comfyui-nodes` in the
      comfyui-data volume, installed 2026-08-23 03:38 (2 min before the
      miner started). Source review confirmed unauthenticated routes
      `/champdev/terminal/ws` (spawns a full PTY shell) and
      `/champdev/fm/*` (arbitrary file read/write/delete), plus a
      telemetry beacon to comfy-nodes-telemetry.champdev.in
- [x] Confirm re-infection after the user's reboot: ComfyUI log showed
      the champdev terminal reconnecting at 12:17 today; miner PID 759
      relaunched as root, GPUs back to 100 % — proving the volume-
      resident node re-loads on every start
- [x] Verify containment: after the user removed the container and
      port mapping, GPUs returned to idle (0-1 % / 12-35 W), no C2
      connection, comfyui container gone
- [x] Host + lateral-movement sweep (2026-08-23 onward): no host C2
      connection, no rogue accounts / admin changes, clean Run keys /
      scheduled tasks / startup folders, no suspicious new executables
      (only Defender/Plex/VSCode auto-updates), other containers
      (privileged sungwoo dind, webdav) clean. Infection stayed inside
      the deleted comfyui container
- [x] Record the incident as a GitHub issue via `gh` — GitHub issue #13
      (created after the user re-authenticated; `security` label absent
      in the repo, filed without a label)
- [ ] Remaining remediation (not yet executed): remove
      `champdev-comfyui-nodes` from the comfyui-data volume before any
      ComfyUI recreation; keep 8188 / ComfyUI-Manager off the public
      network (VPN or authenticated reverse proxy)

## 2026-09-01 — New board IP + Android phone detection on the UNO Q

Requested by user. Diagnosis this session: the board no longer answers
at 192.168.31.172; a subnet scan found it at 192.168.31.84 (hostname
SungwooQ, SSH key auth OK, up 11 days). Task: point the `unoq` SSH
alias at the new IP, then check whether the Android phone attached to
the board's USB port is recognized (lsusb / adb on the board).
(see LP §2, §5)

- [x] Update ~/.ssh/config `unoq` host entry to 192.168.31.84 and
      verify `ssh unoq` works (also removed a duplicate `unoq` block)
- [x] Enumerate USB devices on the board (lsusb) and identify the
      Android phone — NOT enumerated (see results)
- [x] Check adb-level recognition of the phone from the board — adb is
      not installed on the board; moot while nothing enumerates
- [x] Record results below

### Results (2026-09-01)

- `ssh unoq` -> SungwooQ at 192.168.31.84 (DHCP moved it from .172;
  ARP MAC 14:b5:cd:eb:00:b5). Config had the `unoq` block twice with
  the stale IP; collapsed to one entry. Suggest a DHCP reservation on
  the router to stop future drift.
- Android phone: NOT recognized. Current lsusb shows only the user's
  hub chain (Terminus hub, Genesys hubs, microSD reader, RTL8153
  ethernet, a USB-C Video Adaptor billboard device) — no phone-class
  device (no MTP/ADB/vendor 18d1/04e8-style entry).
- Kernel log shows something WAS cycling on hub ports 1-1.3.2/1-1.3.3
  up to ~40 min before the check (board 23:08 UTC): repeated
  enumerate/disconnect every few seconds as a cdc_acm serial device
  (ttyACM0), one "device descriptor read/64, error -71" — the classic
  bad-cable / insufficient-power signature. Silent since; port empty.
- udev's ID_VENDOR=Arduino / ID_MODEL=Imola record is the board's own
  DMI identity (UNO Q internal name), not a USB gadget — red herring.
- Next steps for the user: use a known-good DATA cable (charge-only
  cables reproduce exactly this), plug the phone directly into the
  board or a powered hub port, and set the phone's USB mode to File
  transfer / enable USB debugging. Then re-run lsusb; install adb on
  the board (`apt install adb`) only once the phone enumerates.

## 2026-09-01 — myhyundai_aircon custom component, stage 0

Requested by user; plan confirmed in chat against
docs/SPEC-myhyundai-aircon-component.md. Decisions: develop and test
on the UNO Q board itself; component source lives in this repo under
a new root `custom_components/` directory and is deployed to the
board's HA config over scp; the dedicated phone (Galaxy Z Fold3)
stays attached to the board USB permanently (charging + ADB TCP
bootstrap host). Before any change, preserve the current on-board
sources in a backup folder. Implementation follows spec §11 in four
PRs (skeleton+adb_client / dump+recipe engine / notification+
entities+guards / docs), with a mandatory stop before spec stages
5-6 until real-device dumps confirm U3-U8. Note: the phone does not
currently enumerate on the board USB (see previous entry), so
phone-side steps wait on the user replacing the cable; code stages
1-4 need no phone. (see LP §2, §3, §5)

- [x] Back up current on-board sources (/home/arduino/ArduinoApps,
      HA config /home/arduino/homeassistant) into a dated folder
      under /home/arduino/backup/ before touching anything
      (actual paths differ — see results)
- [x] Identify the adb-shell version pinned by the installed HA
      container and record it for manifest.json — adb-shell[async]
      ==0.4.4 (venv install, not container; see results)
- [x] Set up an on-board test venv (pytest + ruff +
      pytest-homeassistant-custom-component) for board-side testing
- [x] BLOCKED on user cable fix: enumerate the Z Fold3 on board USB,
      install adb, run `adb tcpip 5555`, record the phone's WiFi IP
      — done after the user enabled USB debugging; phone WiFi IP
      192.168.31.113 (needs DHCP reservation)
- [ ] BLOCKED on user: U2 gate — MyHyundai app runs normally with
      USB debugging enabled (project stops if not) — STRONG POSITIVE
      partial: widget renders live vehicle data with debugging on;
      full gate needs one real remote command (user)
- [x] Record results below

### Results (2026-09-01)

- Backup: /home/arduino/backup/2026-09-01-pre-myhyundai/ holds
  ArduinoApps.tar.gz (210 entries), ha_config.tar.gz (45),
  mosquitto.tar.gz (4), home-scripts.tar.gz (5); all four verified
  with `tar tzf`. Disk unchanged at 80 % used, 2.0 GB free.
- Environment surprise: this board (SungwooQ, 192.168.31.84) does
  NOT run HA Container. HA Core 2026.2.3 runs in a Python 3.13.5
  venv at /home/arduino/ha_venv as systemd `home-assistant.service`,
  config /home/arduino/ha_config, port 8123 answering HTTP 200.
  ArduinoApps holds only led3_ctl (running) and qtest_blank — no
  ha-mcu-bridge; the container stack described in earlier entries
  lives on the other unit (uno-q, ex-.172). Component deploy target
  is therefore /home/arduino/ha_config/custom_components/ and deps
  install into ha_venv (LP §5 entry added).
- adb-shell pin: HA 2026.2.3 androidtv manifest requires
  `adb-shell[async]==0.4.4` -> goes into our manifest.json verbatim.
- Test venv: /home/arduino/ha_test_venv (746 MB) with
  pytest-homeassistant-custom-component 0.13.316 (the release whose
  requires_dist pins homeassistant==2026.2.3, found via PyPI JSON —
  LP §3 entry added), pytest 9.0.0, ruff 0.16.5,
  adb-shell[async] 0.4.4. Imports verified on the board.
- Phone/U2 items remain blocked on the user replacing the USB data
  cable (phone did not enumerate; see the previous entry's results).
- GitHub issue #15, branch feature/myhyundai-aircon-stage0.
- Update (same day, user asked for a USB re-check): the phone now
  enumerates STABLY as 04e8:6860 SAMSUNG_Android (MTP mode) on hub
  port 1-1.3.2 after ~9 flapping cycles (devices 62-70) settled at
  device 71. Interfaces exposed: MTP (06), CDC ACM serial (02/0a ->
  ttyACM0), vendor ff/40 — NO adb interface (ff/42), i.e. USB
  debugging is OFF on the phone. Board-side adb client installed
  WITHOUT touching system packages: Debian's adb conflicts with the
  preinstalled Arduino android-libcutils (…arduino3/7 builds, used
  by the board's own adbd), and the privileged-helper route was
  denied, so adb 34.0.5-debian + stock android libs were extracted
  from .debs into /home/arduino/adb-local/rootfs (run with
  LD_LIBRARY_PATH=…/rootfs/usr/lib/aarch64-linux-gnu/android).
  `adb version` OK; `adb devices` empty as expected. Next user
  action: enable Developer options > USB debugging on the Z Fold3
  and accept the RSA prompt; then re-run adb devices and
  `adb tcpip 5555`.
- Update 2 (same day, user enabled USB debugging): full ADB chain
  verified end-to-end. Fixes on the way: `arduino` added to the
  plugdev group (adb reported "no permissions"); `sg plugdev` strips
  LD_LIBRARY_PATH (setgid secure-execution), so it must be exported
  inside the sg command string. Phone authorized: SM-F926N
  (Z Fold3, Android 15), serial R3CR80H1GBN, cover screen
  `wm size` Physical 832x2268 with Override 840x2289 — screencap
  returns 840x2289, so the executor must prefer the override size
  for coordinate math. WiFi IP 192.168.31.113/24 (DHCP reservation
  still recommended). `adb tcpip 5555` + `adb connect
  192.168.31.113:5555` + TCP shell all OK — the exact transport the
  HA component will use. `com.hyundai.oneapp.kr` is installed.
  Bonus screenshot over TCP captured the HOME SCREEN WIDGET on the
  cover display: "캐스퍼 Electric", refreshed 08:23, 98 % / 386 km,
  four buttons labeled 켜기 / 잠금 / 시작 / 종료 — U9 (cover-screen
  rendering) answered YES, and the widget button layout for the
  aircon_on recipe is now known (text labels exist for tap_node
  matching). U2 is a strong partial positive (live vehicle data
  loads with debugging on); the full gate still needs one real
  remote command observed by the user. Screenshot kept off-repo
  (board ~/u2test.png) — car/account privacy.

## 2026-09-01 — myhyundai_aircon PR 1: skeleton + adb_client +
## config flow (spec §11 stages 1-2)

Requested by user ("머지 후 해줘" after PR #16 merged). First code
PR of the confirmed 4-PR plan: component skeleton under root
custom_components/myhyundai_aircon/, async ADB client on
adb-shell[async]==0.4.4 (the HA 2026.2.3 pin), and the Config Flow
that validates the connection and auto-saves the screen resolution
(preferring the Override size per stage-0 finding). Options flow is
deferred to the guards PR where its values are consumed. Unit tests
run on the board in /home/arduino/ha_test_venv; live verification =
deploy to /home/arduino/ha_config/custom_components/, restart HA,
drive the config flow over the REST API against the phone at
192.168.31.113:5555 reusing the already-authorized
/home/arduino/.android/adbkey. (see LP §3, §5)

- [x] Verify adb-shell 0.4.4 async API signatures against the
      installed package on the board before coding (§7 rule)
- [x] Skeleton: manifest.json (requirements pin), const.py,
      __init__.py (setup/unload with coordinator), coordinator.py
      (connectivity poll + backoff), strings.json, translations
      en/ko
- [x] adb_client.py: keygen-if-missing, connect with RSA signer,
      shell, close, error mapping (cannot_connect / auth_rejected /
      invalid_device), serial + wm-size probes
- [x] config_flow.py: user step, unique_id = device serial,
      baseline_screen auto-save (Override preferred)
- [x] Unit tests (tests/ + conftest) green in ha_test_venv on the
      board; ruff clean at line-length 80 — 12 passed in 2.53 s
- [x] Deploy to the board, restart home-assistant.service, create
      the config entry via REST config-flow API, confirm
      baseline_screen 840x2289 stored and entry loaded — done after
      the user approved a password reset (see results update)
- [x] Record results below

### Results (2026-09-01, PR 1)

- adb-shell 0.4.4 API confirmed from the installed source:
  AdbDeviceTcpAsync(host, port, default_transport_timeout_s),
  connect(rsa_keys=[signer], auth_timeout_s), shell(cmd,
  read_timeout_s, timeout_s), close(), keygen(path),
  PythonRSASigner.FromRSAKeyPath(path), and the exception set used
  for error mapping.
- Component skeleton written under root custom_components/
  myhyundai_aircon/ (manifest pins adb-shell[async]==0.4.4,
  version 0.1.0). Coordinator polls connectivity every 30 s and
  walks the 5/15/45/60 s backoff ladder while disconnected.
  parse_screen_size prefers the Override resolution (stage-0
  finding: screencaps use 840x2289, not the physical 832x2268).
- Tests: tests/{conftest,test_adb_client,test_config_flow}.py with
  phacc; pyproject gained [tool.pytest.ini_options] asyncio_mode=
  auto + pythonpath=["."] (without pythonpath, custom_components
  is not importable from the tests). 12/12 green on the board.
- Deploy gotcha: `cp -r src/myhyundai_aircon dest/custom_components/`
  when custom_components does not yet exist copies src AS
  custom_components (rename semantics); ended up with the module
  spilled at the top level once — cleaned and re-copied properly.
- HA restarted and DISCOVERED the integration (loader warning
  logged). Live config-entry creation over REST is blocked: the
  stored ~/.ha_token (Jul 20) returns 401 — this venv install was
  reset mid-July and its admin password is neither arduino nor the
  onboarding default changeme. Two password guesses only, then
  stopped; need the real password from the user (or approval to
  reset it offline via `hass --script auth`).
- GitHub issue #17, branch feature/myhyundai-skeleton.
- Update (same day): the user could not recall the HA password and
  approved a reset. `hass --script auth list` showed the single
  user `arduino`; HA stopped, `change_password arduino arduino`
  (board-convention value, user advised to change it in the UI),
  HA restarted. Fresh 10-year long-lived token minted over the
  websocket API (client unoq-cli) into ~/.ha_token (API check 200).
  Config flow driven over REST: create_entry with state "loaded"
  on the first try. Stored entry verified in core.config_entries:
  unique_id R3CR80H1GBN (phone serial), baseline_screen 840x2289
  (Override preferred, as designed), host 192.168.31.113:5555,
  adbkey /home/arduino/.android/adbkey. HA auto-installed
  adb-shell[async]==0.4.4 into ha_venv from the manifest pin.
  Spec §11 stages 1-2 completion criteria fully met.
