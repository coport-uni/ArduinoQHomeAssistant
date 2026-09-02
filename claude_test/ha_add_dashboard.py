"""Create a Home Assistant dashboard and load its config from YAML.

Dashboards live in .storage and there is no REST endpoint for them, so
both steps go over the WebSocket API: lovelace/dashboards/create makes
the sidebar entry, lovelace/config/save fills it in. Re-running is
safe -- an existing dashboard with the same url_path is reused and its
config overwritten.

Run on the board with the HA venv python (the system python has no
aiohttp):

    /home/arduino/ha_venv/bin/python3 ha_add_dashboard.py \\
        --config unoq-leds.yaml --url-path uno-q --title "UNO Q"
"""

import argparse
import asyncio
import sys

import aiohttp
import yaml

DEFAULT_BASE = "http://localhost:8123"
DEFAULT_TOKEN_FILE = "/home/arduino/.ha_token"


async def _request(ws, message_id, payload):
    """Send one WebSocket command and return its result message."""
    await ws.send_json({"id": message_id, **payload})
    while True:
        message = await ws.receive_json()
        if message.get("id") == message_id:
            return message


async def install(base, token, config, url_path, title, icon):
    """Create the dashboard if needed, then save its config."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{base}/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": token})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                raise SystemExit(f"auth failed: {auth}")

            listed = await _request(ws, 1, {"type": "lovelace/dashboards/list"})
            existing = [
                d for d in listed["result"] if d["url_path"] == url_path
            ]
            if existing:
                print(f"dashboard {url_path} already exists, reusing")
            else:
                created = await _request(
                    ws,
                    2,
                    {
                        "type": "lovelace/dashboards/create",
                        "url_path": url_path,
                        "title": title,
                        "icon": icon,
                        "show_in_sidebar": True,
                        "require_admin": False,
                    },
                )
                if not created.get("success"):
                    raise SystemExit(f"create failed: {created}")
                print(f"dashboard {url_path} created")

            saved = await _request(
                ws,
                3,
                {
                    "type": "lovelace/config/save",
                    "url_path": url_path,
                    "config": config,
                },
            )
            if not saved.get("success"):
                raise SystemExit(f"config save failed: {saved}")
            print(f"config saved: {len(config.get('views', []))} view(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="dashboard YAML")
    parser.add_argument("--url-path", required=True, help="e.g. uno-q")
    parser.add_argument("--title", required=True, help="sidebar title")
    parser.add_argument("--icon", default="mdi:led-on")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    with open(args.token_file, encoding="utf-8") as f:
        token = f.read().strip()

    # A url_path without a hyphen is rejected by HA as ambiguous with
    # the built-in panels, which is easy to trip over.
    if "-" not in args.url_path:
        sys.exit("url_path must contain a hyphen")

    asyncio.run(
        install(
            args.base,
            token,
            config,
            args.url_path,
            args.title,
            args.icon,
        )
    )


if __name__ == "__main__":
    main()
