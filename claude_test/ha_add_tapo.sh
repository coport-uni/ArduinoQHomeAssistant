#!/bin/bash
# Add a Tapo/Kasa device to Home Assistant by MAC via the tplink config flow.
# Usage: TAPO_USER=... TAPO_PASS=... bash ha_add_tapo.sh <device_mac_lowercase>
set -euo pipefail
MAC="$1"
BASE=http://localhost:8123
TOKEN=$(cat /home/arduino/.ha_token)
AUTH="Authorization: Bearer $TOKEN"
CT="Content-Type: application/json"

jqpy() { python3 -c "import sys,json;d=json.load(sys.stdin);$1"; }

resp=$(curl -s --max-time 120 -X POST $BASE/api/config/config_entries/flow \
  -H "$AUTH" -H "$CT" -d '{"handler":"tplink"}')
fid=$(echo "$resp" | jqpy 'print(d["flow_id"])')

resp=$(curl -s --max-time 120 -X POST $BASE/api/config/config_entries/flow/$fid \
  -H "$AUTH" -H "$CT" -d '{}')
step=$(echo "$resp" | jqpy 'print(d.get("step_id") or d.get("type"))')
echo "after discovery: step=$step"

resp=$(curl -s --max-time 120 -X POST $BASE/api/config/config_entries/flow/$fid \
  -H "$AUTH" -H "$CT" -d "{\"device\":\"$MAC\"}")
step=$(echo "$resp" | jqpy 'print(d.get("step_id") or d.get("type"))')
echo "after pick_device($MAC): step=$step"

if [ "$step" != "create_entry" ] && echo "$resp" | grep -q '"username"'; then
  resp=$(curl -s --max-time 180 -X POST $BASE/api/config/config_entries/flow/$fid \
    -H "$AUTH" -H "$CT" \
    -d "{\"username\":\"$TAPO_USER\",\"password\":\"$TAPO_PASS\"}")
  step=$(echo "$resp" | jqpy 'print(d.get("step_id") or d.get("type"))')
  echo "after credentials: step=$step"
fi

echo "$resp" | jqpy 'print("RESULT:", d.get("type"), "| title:", d.get("title"), "| reason:", d.get("reason"), "| errors:", d.get("errors"))'
