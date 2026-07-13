"""Unicast Tapo/Kasa discovery probe across a whole /24 subnet.

Catches devices that ignore ICMP ping (so an ARP sweep misses them).
Usage: python probe_all.py [subnet_prefix]   (default: 192.168.1)
"""
import asyncio
import sys

from kasa import Discover

PREFIX = sys.argv[1] if len(sys.argv) > 1 else "192.168.1"
SEM = asyncio.Semaphore(64)
found = []


async def probe(ip):
    async with SEM:
        try:
            dev = await Discover.discover_single(ip, discovery_timeout=3)
            info = dev._discovery_info or {}
            model = (info.get("device_model")
                     or info.get("result", {}).get("device_model")
                     or getattr(dev, "model", "?"))
            found.append((ip, model, getattr(dev, "mac", "?")))
        except Exception as e:
            if "Authentication" in type(e).__name__:
                found.append((ip, f"auth-required: {e}", "?"))


async def main():
    ips = [f"{PREFIX}.{i}" for i in range(1, 255)]
    await asyncio.gather(*(probe(ip) for ip in ips))
    print(f"TAPO/KASA devices found: {len(found)}")
    for ip, model, mac in sorted(found):
        print(f"  {ip}  {model}  {mac}")


asyncio.run(main())
