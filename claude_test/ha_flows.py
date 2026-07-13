"""Check HA in-progress config flows via websocket API."""
import asyncio, json, os, sys
import aiohttp

TOKEN = os.environ["HA_TOKEN"]

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("http://localhost:8123/api/websocket") as ws:
            await ws.receive_json()  # auth_required
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            msg = await ws.receive_json()
            if msg.get("type") != "auth_ok":
                print("AUTH FAILED", msg); sys.exit(1)
            await ws.send_json({"id": 1, "type": "config_entries/flow/progress"})
            msg = await ws.receive_json()
            flows = msg.get("result", [])
            print(f"in-progress flows: {len(flows)}")
            for f in flows:
                print(json.dumps({k: f.get(k) for k in ("flow_id","handler","context")}))
asyncio.run(main())
