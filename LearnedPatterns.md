# LearnedPatterns.md

Lessons distilled from the completed items in `ToDo.md`, per CLAUDE.md
§9–10. ToDo sections are numbered in file order: #1 WiFi/HA/Tapo
detection, #2 reproducibility guide, #3 WiFi + VS Code Remote-SSH,
#4 Tapo registration + toggle test, #5 guide extension.

## §1. Recurring Issues

- **Problem**: Root-level changes needed where passwordless sudo is
  unavailable (host USB perms in #1, board sshd host keys in #3).
  **Cause**: Neither the container host user nor the board `arduino`
  user has passwordless sudo, but both are in the `docker` group.
  **Fix**: One-shot privileged helper container (`docker run --privileged
  --pid=host ... nsenter -t 1` on the board; chmod helper on the host).
  **Rule**: Always consider a privileged docker helper for root tasks
  before asking the user for a sudo password. (from ToDo#1, ToDo#3)

## §2. Solved Gotchas

- **Problem**: SSH to the UNO Q refused on port 22 although
  openssh-server is installed and enabled. **Cause**: Fresh image ships
  with no SSH host keys; `sshd -t` fails at ExecStartPre. **Fix**:
  `ssh-keygen -A && systemctl restart ssh` as root. **Rule**: Always
  check `journalctl -u ssh` for "no hostkeys available" before deeper
  debugging of SSH on a fresh board. (from ToDo#3)
- **Problem**: `ssh arduino@<board-ip>` tried port 6800 and failed.
  **Cause**: This dev container sets `Port 6800` globally in
  `/etc/ssh/ssh_config`. **Fix**: Explicit `Port 22` in the per-host
  `~/.ssh/config` entry. **Rule**: Always pin `Port` in per-host SSH
  config entries created in this container. (from ToDo#3)
- **Problem**: HA API calls started failing ~30 min after onboarding.
  **Cause**: Onboarding-issued access tokens are short-lived. **Fix**:
  Mint a 10-year long-lived token over the WebSocket API
  (`auth/long_lived_access_token`). **Rule**: Never persist the
  onboarding token; always mint a long-lived token immediately.
  (from ToDo#4)
- **Problem**: Tapo KLAP auth rejected valid-looking credentials.
  **Cause**: KLAP hashes email and password case-sensitively. **Fix**:
  Verify exact-case credentials with python-kasa before the HA flow.
  **Rule**: Always pre-check Tapo credentials with python-kasa before
  registering in HA. (from ToDo#4)
- **Problem**: A pre-toggle safety check read 0.0 W and was taken as
  "no load", but HA history showed 89.4 W in the first ON window — a
  ~90 W device was attached and got power-cycled. **Cause**: A plug
  whose relay is off always reports 0 W regardless of what is plugged
  in. **Fix**: Read the consumption sensor while the plug is ON (or
  inspect the socket) before toggle tests; guide step 8 CAUTION now
  says so. **Rule**: Never treat an off-state 0 W reading as proof
  that a smart plug has no load. (from ToDo#8)

- **Problem**: A Home Assistant automation saved successfully through
  the config API never ran, and no error appeared anywhere. **Cause**:
  `configuration.yaml` built by this repo's onboarding scripts holds
  only `default_config:` and the themes include, missing the stock
  `automation: !include automations.yaml` line -- so HA writes
  `automations.yaml` happily and then never reads it. **Fix**: Append
  the include (after backing the file up), create an empty
  `automations.yaml`, and call `automation.reload`; no restart needed.
  **Rule**: Always confirm an automation appeared as an
  `automation.*` entity after installing it -- a "result: ok" from the
  config API only means the file was written. (from ToDo#44)

- **Problem**: An automation keyed on "the phone is not on the home
  WiFi" would have started the car every time the user arrived at the
  lab. **Cause**: The rule was written from the two networks the user
  named, but the recorder shows the phone spends most of its day on a
  third one. **Fix**: Read the entity's actual history before choosing
  the set, and list every place the user normally is. **Rule**: Always
  check the recorder for where a presence-ish sensor really sits
  before writing a rule about where it is not. (from ToDo#47)
- **Problem**: A trigger written as "SSID is not one of ours" also
  matches `unavailable` and `unknown`, so losing contact with the
  phone would have started the vehicle. **Cause**: Those states mean
  "no report", not "somewhere else", but a `not in` test cannot tell
  the difference. **Fix**: List `unavailable` and `unknown` alongside
  the known networks in the exclusion set. **Rule**: Never let
  `unavailable`/`unknown` fall into the default branch of an
  automation whose action has a physical consequence. (from ToDo#47)

## §3. Library Quirks

- **Problem**: `arduino-app-cli app ps` crashes with `panic: not
  implemented`. **Cause**: Unimplemented subcommand in v0.6.6. **Fix**:
  Use `arduino-app-cli app list` or `docker ps`. **Rule**: Never rely on
  `app ps`; use `app list` for app status. (from ToDo#3)
- **Problem**: Tapo plugs missed by ping/ARP sweeps. **Cause**: The
  plugs ignore ICMP. **Fix**: python-kasa unicast probe across the /24
  (claude_test/probe_all.py). **Rule**: Always use protocol-level
  discovery for Tapo devices, not ping sweeps. (from ToDo#1)
- **Problem**: HA discovery flows invisible over REST. **Cause**:
  In-progress config flows are exposed only via the WebSocket API.
  **Fix**: Query `config_entries/flow/progress` over WebSocket
  (claude_test/ha_flows.py). **Rule**: Always use the WebSocket API for
  HA discovery-flow inspection. (from ToDo#1)
- **Problem**: WebSocket scripts fail on the board's system Python.
  **Cause**: No aiohttp installed system-wide. **Fix**: Run them inside
  the HA container. **Rule**: Always run HA WebSocket tooling inside the
  `homeassistant` container. (from ToDo#4)
- **Problem**: After a board reboot, HA and Mosquitto came back but
  the App Lab app stayed stopped (MCU entities unavailable, matrix
  dark). **Cause**: App Lab apps are not auto-started at boot unless
  registered as the "default app" with the arduino-app-cli daemon.
  **Fix**: `arduino-app-cli properties set default <app_path>`.
  **Rule**: Always register a long-running App Lab app as the default
  app so it survives reboots. (from ToDo#10)
- **Problem**: App python crashed with ModuleNotFoundError after
  adding psutil to requirements.txt and running `app restart`.
  **Cause**: arduino-app-cli reuses the cached venv in
  `<app>/.cache/.venv` and does not reinstall on requirements
  changes. **Fix**: `app stop`, `rm -rf <app>/.cache/.venv`,
  `app start`. **Rule**: Always wipe the app's `.cache/.venv` after
  changing requirements.txt. (from ToDo#9)
- **Problem**: Driving the UNO Q 8x13 LED matrix seemed to need a
  library and the raw frame bit order was undocumented. **Cause**:
  `matrixBegin()`/`matrixWrite(uint32_t[4])` are exported by the base
  firmware (variant syms-dynamic.ld) and official examples call them
  via bare `extern "C"` declarations. **Fix**: Decoded the official
  air-quality icon frames both ways
  (claude_test/decode_matrix_frame.py): pixel `i = row*13 + col` ->
  `word[i/32]`, bit `i%32`, row 0 top, col 0 left. **Rule**: Always
  determine undocumented frame formats by decoding known-good example
  assets before resorting to on-hardware trial. (from ToDo#9)

- **Problem**: The post-write ruff hook rejected code hand-wrapped to
  80 columns ("Would reformat") although `ruff format --line-length 80`
  accepted it. **Cause**: The repo had no pyproject.toml, so the hook's
  bare `ruff format --check` fell back to Ruff's 88-column default,
  which re-joins wrapped lines that fit under 88. **Fix**: Root
  pyproject.toml with `[tool.ruff] line-length = 80` (PR #10).
  **Rule**: Always give a CommonClaude repo a root pyproject.toml with
  line-length 80 before writing Python. (from ToDo#12)

- **Problem**: Needed the pytest-homeassistant-custom-component
  release matching the installed HA version; the package pins
  `homeassistant==X` exactly and a mismatched pick drags in a
  different HA. **Cause**: phacc tracks HA releases one-to-one but
  its version numbers (0.13.x) do not encode the HA version.
  **Fix**: Query PyPI JSON per release and read `requires_dist`
  (`pypi.org/pypi/<pkg>/<ver>/json`); 0.13.316 pins
  homeassistant==2026.2.3. **Rule**: Always select phacc by its
  `requires_dist` homeassistant pin, never by "latest".
  (from ToDo#17)

- **Problem**: A script streamed over `ssh 'bash -s' < script.sh`
  silently stopped after its first adb command (no output, exit 0).
  **Cause**: `adb shell` reads stdin for interactive passthrough
  and consumed the rest of the script that bash had not read yet.
  **Fix**: scp the script to the board and run it from a file (or
  redirect each adb call's stdin from /dev/null). **Rule**: Never
  stream a script over ssh stdin if it invokes adb (or any
  stdin-reading command); copy it to a file first. (from ToDo#21)

- **Problem**: A timestamp sensor parsed from Korean on-screen
  text landed 9 hours off. **Cause**: A headlessly onboarded HA
  keeps time_zone=UTC, so dt_util.now() anchors local-looking
  times wrongly; the REST /api/config/core/update endpoint
  silently ignored a time_zone change. **Fix**: Set it over the
  WebSocket API (`config/core/update` with time_zone) and restart
  HA. **Rule**: Always set the HA core time zone right after a
  headless onboarding, and use the WebSocket API for core config
  changes. (from ToDo#26)
- **Problem**: `analogWrite()` on the UNO Q's LED3 channels did
  nothing — the LED stayed dark through a full brightness sweep —
  even though the devicetree maps those pads to pwm5 channels.
  **Cause**: The Arduino Zephyr core's `analogWrite()` only calls
  `pwm_set_pulse_dt()`; it never re-applies pinctrl. An earlier
  `pinMode()`/`digitalWrite()` on the same pad had already switched
  it to GPIO, and the PWM signal never reached it again. **Fix**:
  Keep the PWM-driven pins out of every GPIO code path (no
  `pinMode`, no pin table entry) and initialise them with
  `analogWrite(0)`; verified by re-flashing with the GPIO call
  removed. **Rule**: Never mix the GPIO and PWM APIs on one pad in
  a single MCU session — the first `pinMode` wins until reset.
  (from ToDo#40)
- **Problem**: A sketch calling the core's `pwm_pin_index()` failed
  to link (`undefined reference`), which looked like PWM being
  unavailable. **Cause**: GCC inlines it into `analogWrite`, so no
  symbol survives in `core.a`; separately, `syms-dynamic.ld`
  exports no PWM symbols at all, which is also a red herring
  because Zephyr reaches the driver through the device API pointer
  rather than an exported syscall. **Fix**: Verify the pin -> PWM
  channel mapping statically from the devicetree
  (`digital-pin-gpios` index vs `pwm-pin-gpios`) instead of at
  runtime. **Rule**: Never conclude a peripheral is missing from a
  link error against a core-internal helper; check the devicetree
  and the exported symbol table separately. (from ToDo#40)

- **Problem**: An automation triggered by `homeassistant.start` can
  fire before the entity it drives exists. **Cause**: MQTT Discovery
  re-creates the bridge's light entities from retained config topics
  *after* the start event -- ~20 s into a restart on this board.
  **Fix**: Add a second trigger on the target entity leaving
  `unavailable`, which also covers the App Lab app restarting on its
  own (the sketch turns both LEDs off in `setup()`, and the MQTT LWT
  makes the entity unavailable meanwhile). **Rule**: Never rely on
  `homeassistant.start` alone to restore state on an MQTT-discovered
  entity; trigger on its recovery from `unavailable` too.
  (from ToDo#44)

## §4. Workflow Lessons

- **Problem**: CLAUDE.md §4 requires GitHub issue/branch/PR but the repo
  has no remote (and initially no commits). **Cause**: Repository not
  yet published. **Fix**: Record the deviation explicitly in each
  ToDo.md entry and continue with ToDo.md-only tracking. **Rule**:
  Always record §4 workflow deviations in the ToDo.md entry until the
  repo gains a remote. (Resolved 2026-07-14: remote exists; full
  issue/branch/PR flow used from ToDo#8 on.) (from ToDo#1, ToDo#3)
- **Problem**: Repo-local board scripts were copied with `adb push`
  before every run, so the board copy drifted from the repo. **Cause**:
  Two-step copy-then-run workflow. **Fix**: Stream the script over SSH
  stdin: `ssh <board> 'bash -s -- <args>' < claude_test/<script>.sh`.
  **Rule**: Always prefer `bash -s` over-SSH streaming for repo-local
  board scripts; copy only files that must persist on the board.
  (from ToDo#8)

- **Problem**: Hardware behaviour needed confirming while the user was
  out of the room. **Cause**: LED colour is only observable on the
  physical board. **Fix**: Drive the input through the REST API
  (overwriting a companion-app sensor's state is temporary -- the phone
  pushes its real value back on the next update) and read the result
  off a webcam pointed at the board (`claude_test/cam_snap.py`).
  **Rule**: Always look for an existing camera on the rig before
  reporting a hardware change as unverified. (from ToDo#44)

- **Problem**: The trigger and hold time of an automation that starts
  a real car could not be tested by firing it. **Cause**: Verifying
  the trigger and verifying the action are the same act when the
  action has a physical consequence. **Fix**: Install a probe
  automation carrying the identical `value_template` and `for:` whose
  action is `system_log.write`, exercise it through the REST API, then
  delete it and install the real one
  (`claude_test/away_trigger_probe.yaml`). **Rule**: Always split
  trigger verification from action verification when the action is not
  free to repeat. (from ToDo#47)

## §5. Environment Specifics

- **Problem**: Assumed USB was required to flash the UNO Q's MCU.
  **Cause**: On the UNO Q the STM32U585 is flashed by the board's own
  Linux side (OpenOCD, SWD GPIO bitbang), triggered by
  `arduino-app-cli app start/restart`. **Fix**: Full-board programming
  over WiFi+SSH only (verified ~98 s first build+flash). **Rule**:
  Always prefer WiFi+SSH for UNO Q development; USB is only needed for
  the one-time ADB bootstrap. (from ToDo#3)
- **Problem**: ADB access breaks after the board is replugged.
  **Cause**: `/dev/bus/usb` permissions reset on replug; host user
  lacks passwordless sudo. **Fix**: Re-run the privileged docker chmod
  helper (see docs/home-assistant-uno-q-guide.md). **Rule**: Always
  re-apply the USB permission fix after replugging the board.
  (from ToDo#1)
- **Problem**: Concern that vscode-server + Home Assistant exceed board
  RAM. **Cause**: Assumed 2 GB variant. **Fix**: Board "SungwooQ" is
  the 4 GB variant (3.6 GiB visible, ~2.4 GiB available with HA up).
  **Rule**: Always check `free -h` before capacity decisions; this
  board comfortably runs HA + vscode-server. (from ToDo#3)

- **Problem**: The board reachable as `unoq` (SungwooQ, .84) was
  assumed to run HA Container per the guide, but `docker ps` showed
  no `homeassistant` container and `/home/arduino/homeassistant`
  did not exist. **Cause**: This unit runs HA Core 2026.2.3 in a
  Python 3.13 venv (`/home/arduino/ha_venv`) as systemd service
  `home-assistant.service` with config in `/home/arduino/ha_config`;
  the container layout belongs to the other unit (uno-q, ex-.172).
  **Fix**: Probed process/systemd/port level, not just docker.
  Custom components go in `/home/arduino/ha_config/custom_components`
  and integration deps install into `ha_venv`. **Rule**: Always
  identify the HA install method (container vs venv/systemd) on a
  board before using guide paths — two UNO Q units exist with
  different layouts. (from ToDo#17)

## §99. Uncategorized

- (empty)
