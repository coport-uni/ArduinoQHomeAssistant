"""Mint a HA long-lived access token. Env: HA_SHORT_TOKEN."""

import asyncio
import os
import sys

import aiohttp


async def main():
    tok = os.environ["HA_SHORT_TOKEN"]
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("http://localhost:8123/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": tok})
            msg = await ws.receive_json()
            if msg["type"] != "auth_ok":
                print("AUTH FAILED", msg, file=sys.stderr)
                sys.exit(1)
            await ws.send_json(
                {
                    "id": 1,
                    "type": "auth/long_lived_access_token",
                    "client_name": "unoq-cli",
                    "lifespan": 3650,
                }
            )
            msg = await ws.receive_json()
            print(msg["result"], end="")


asyncio.run(main())
