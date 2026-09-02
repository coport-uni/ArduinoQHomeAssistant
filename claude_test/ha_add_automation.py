"""Push a YAML automation into Home Assistant and reload automations.

The config API (POST /api/config/automation/config/<id>) writes the
automation into automations.yaml for us, so the repo keeps the source
of truth and the board keeps a file HA can edit in the UI afterwards.
Re-running is safe -- the same automation id is overwritten in place.

The include line is a prerequisite this script does NOT add: a
configuration.yaml without `automation: !include automations.yaml`
loads zero automations no matter what the config API writes, and
editing configuration.yaml is left as a deliberate manual step (back
it up first). The script checks the automation actually turned up
after the reload, so a missing include shows as a clear failure.

Run on the board with the HA venv python (the system python has no
yaml):

    /home/arduino/ha_venv/bin/python3 ha_add_automation.py \
        --config phone-wifi-led4.yaml --id phone_wifi_led4
"""

import argparse
import json
import urllib.error
import urllib.request

import yaml

DEFAULT_BASE = "http://localhost:8123"
DEFAULT_TOKEN_FILE = "/home/arduino/.ha_token"

# Keys the config API rejects or ignores; `id` is carried in the URL.
STRIPPED_KEYS = ("id",)


def _post(base, token, path, payload):
    """POST one JSON payload to Home Assistant and return the reply."""
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"POST {path} failed: {e.code} {e.read().decode()}")
    return json.loads(body) if body.strip() else {}


def _get(base, token, path):
    """GET one JSON document from Home Assistant."""
    request = urllib.request.Request(
        f"{base}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"GET {path} failed: {e.code} {e.read().decode()}")


def install(base, token, config, automation_id):
    """Store the automation, reload, and confirm the entity exists."""
    payload = {k: v for k, v in config.items() if k not in STRIPPED_KEYS}
    result = _post(
        base,
        token,
        f"/api/config/automation/config/{automation_id}",
        payload,
    )
    print(f"stored automation {automation_id}: {result}")

    _post(base, token, "/api/services/automation/reload", {})
    print("automations reloaded")

    entity_id = f"automation.{config['alias'].lower().replace(' ', '_')}"
    states = _get(base, token, "/api/states")
    found = [
        s
        for s in states
        if s["entity_id"].startswith("automation.")
        and s["attributes"].get("id") == automation_id
    ]
    if not found:
        raise SystemExit(
            f"automation {automation_id} did not load -- is "
            f"`automation: !include automations.yaml` present in "
            f"configuration.yaml? (looked for {entity_id})"
        )
    print(f"loaded as {found[0]['entity_id']} ({found[0]['state']})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="automation YAML")
    parser.add_argument("--id", required=True, help="automation id")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    with open(args.token_file, encoding="utf-8") as f:
        token = f.read().strip()

    install(args.base, token, config, args.id)


if __name__ == "__main__":
    main()
