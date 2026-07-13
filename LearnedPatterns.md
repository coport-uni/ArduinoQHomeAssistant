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

## §4. Workflow Lessons

- **Problem**: CLAUDE.md §4 requires GitHub issue/branch/PR but the repo
  has no remote (and initially no commits). **Cause**: Repository not
  yet published. **Fix**: Record the deviation explicitly in each
  ToDo.md entry and continue with ToDo.md-only tracking. **Rule**:
  Always record §4 workflow deviations in the ToDo.md entry until the
  repo gains a remote. (from ToDo#1, ToDo#3)

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

## §99. Uncategorized

- (empty)
