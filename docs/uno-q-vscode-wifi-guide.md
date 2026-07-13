# Arduino UNO Q — Full-Board Development over WiFi with VS Code

This guide sets up an Arduino UNO Q so the **entire board** — the Linux
side (Qualcomm QRB2210 MPU, Debian) *and* the Arduino side (STM32U585
MCU) — can be programmed **over WiFi only**, from VS Code, with no USB
cable after the one-time bootstrap.

Why this works: on the UNO Q the MCU is not flashed from your PC. The
sketch is compiled *on the board's Linux side* and flashed to the
STM32U585 through an on-board OpenOCD SWD (GPIO bitbang) link. So once
you can SSH into the Linux side over WiFi, you can program everything.

Verified on: board "SungwooQ" (Debian 13, aarch64, 4 GB RAM variant,
`arduino-app-cli` v0.6.6), 2026-07-13.

## Prerequisites

- The board is on your WiFi network. If not, configure it with `nmcli`
  over ADB — see `docs/home-assistant-uno-q-guide.md` for WiFi and ADB
  setup (including the USB permission fix).
- ADB access to the board for the one-time SSH bootstrap
  (`adb devices` shows the board).
- Board IP address (`adb shell ip addr show wlan0`). Recommended: give
  the board a fixed DHCP lease in your router so the IP never changes.

## 1. One-time: enable SSH on the board

On a fresh UNO Q image, `openssh-server` is installed and enabled but
**fails to start because no SSH host keys exist**:

```bash
adb shell systemctl is-active ssh        # "failed"
adb shell journalctl -u ssh -n 5         # "sshd: no hostkeys available -- exiting."
```

Generating host keys needs root. If you know the `arduino` user's sudo
password, this is simply:

```bash
adb shell   # then on the board:
sudo ssh-keygen -A && sudo systemctl restart ssh
```

Without the password, use the fact that `arduino` is in the `docker`
group and the stock image ships `python:3.12-alpine`. A privileged
helper container can enter the host namespaces and do the same as root:

```bash
adb shell "docker run --rm --privileged --pid=host python:3.12-alpine \
    nsenter -t 1 -m -u -i -n -p -- \
    sh -c 'ssh-keygen -A && systemctl restart ssh && systemctl is-active ssh'"
# expected output: "ssh-keygen: generating new host keys: ..." then "active"
```

`ssh.service` is already enabled, so sshd starts automatically on every
boot from now on.

## 2. One-time: passwordless key authentication

On your development machine:

```bash
# Generate a key if you do not have one.
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# Install the public key on the board via ADB.
PUB=$(cat ~/.ssh/id_ed25519.pub)
adb shell "mkdir -p ~/.ssh && chmod 700 ~/.ssh \
    && grep -qF '$PUB' ~/.ssh/authorized_keys 2>/dev/null \
    || echo '$PUB' >> ~/.ssh/authorized_keys; \
    chmod 600 ~/.ssh/authorized_keys"
```

Add a host alias to `~/.ssh/config` (adjust the IP):

```
Host sungwooq 192.168.1.232
    HostName 192.168.1.232
    User arduino
    Port 22
```

State `Port 22` explicitly: some environments (including this dev
container) set a different default port globally in
`/etc/ssh/ssh_config`, and the per-host entry must win.

Verify: `ssh sungwooq hostname` should print the board name with no
password prompt.

## 3. VS Code Remote-SSH onto the board

1. On the machine where the VS Code **UI** runs, install the
   *Remote - SSH* extension and add the same `Host` block as above to
   that machine's `~/.ssh/config` (and its key to the board, step 2).
2. If that machine is not on the board's LAN, hop through a machine
   that is:

   ```
   Host sungwooq
       HostName 192.168.1.232
       User arduino
       Port 22
       ProxyJump user@lan-gateway-host
   ```

3. `F1` → *Remote-SSH: Connect to Host…* → `sungwooq` → select
   *Linux*. VS Code installs its server on the board and opens a
   remote window.
4. Open the folder `/home/arduino/ArduinoApps` and work directly on
   the board: editor, integrated terminal, and extensions all run
   against the board over WiFi.

Memory note: this board reports 3.6 GiB RAM (4 GB variant) and had
about 2.4 GiB available even with a Home Assistant container running,
so vscode-server fits comfortably. Still, avoid heavyweight extensions
(e.g. Copilot) in the remote window.

## 4. Programming the whole board with arduino-app-cli

An "app" pairs a Python program (Linux/MPU) with an Arduino sketch
(STM32/MCU). All commands below run on the board (VS Code remote
terminal or plain SSH).

```bash
arduino-app-cli app new my_app          # scaffold under ~/ArduinoApps/my_app
arduino-app-cli app start ~/ArduinoApps/my_app    # build + flash + run
arduino-app-cli app restart ~/ArduinoApps/my_app  # rebuild + re-flash after edits
arduino-app-cli app logs ~/ArduinoApps/my_app     # Python stdout
arduino-app-cli app stop ~/ArduinoApps/my_app
arduino-app-cli app list                # running/available apps
```

Generated layout:

```
my_app/
├── app.yaml           # app manifest (name, description, ports, bricks)
├── python/main.py     # runs on the MPU (in a container, venv auto-made)
└── sketch/
    ├── sketch.ino     # runs on the MCU
    └── sketch.yaml    # build profile: fqbn arduino:zephyr:unoq
```

What `app start` does, entirely on-board: compiles the sketch with the
`arduino:zephyr:unoq` core, flashes the STM32U585 via OpenOCD over the
internal SWD link, then provisions and starts the Python side as a
Docker container (`<app>-main-1`). First start of the verification app
took ~100 s; later restarts are faster since libraries are cached.

Verified end to end with `~/ArduinoApps/qtest_blink` (copy kept in
`claude_test/qtest_blink/`): LED blink sketch + Python heartbeat,
deployed and re-flashed over WiFi only, including a round-trip edit of
the blink period (500 ms → 100 ms).

## 5. Day-to-day workflow

1. Open VS Code → Remote-SSH → `sungwooq`.
2. Edit `sketch/sketch.ino` (MCU) and/or `python/main.py` (MPU).
3. In the remote terminal:
   `arduino-app-cli app restart ~/ArduinoApps/<app>`.
4. Check `arduino-app-cli app logs ~/ArduinoApps/<app>`.

No USB cable is involved at any point.

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| Port 22 "connection refused" | sshd has no host keys (fresh image). Do step 1. |
| `ssh` tries a strange port (e.g. 6800) | A global `Port` in `/etc/ssh/ssh_config` on the client. Put `Port 22` in the per-host entry. |
| Board IP changed | DHCP. Reserve a fixed lease in the router; mDNS name (`<hostname>.local`) may also work where mDNS is allowed. |
| `adb devices` empty after board replug | USB device permissions reset on replug — re-apply the fix in `docs/home-assistant-uno-q-guide.md`. |
| `arduino-app-cli app ps` panics with "not implemented" | Known gap in v0.6.6. Use `arduino-app-cli app list` or `docker ps` instead. |
| Library download timeouts during `app start` | Transient network hiccup; harmless if the library is already cached. Re-run if the build itself fails. |
| Remote window sluggish | Check `free -h`; stop unused containers (e.g. Home Assistant) or disable heavy VS Code extensions. |

Security note: after installing keys, password SSH login is still
enabled (Debian default). Consider `PasswordAuthentication no` in
`/etc/ssh/sshd_config.d/` if the board lives on a shared network.
