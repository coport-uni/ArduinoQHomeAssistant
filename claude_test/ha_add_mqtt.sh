#!/bin/bash
# Register the MQTT integration in Home Assistant via config flow.
# Broker defaults to the local Mosquitto at 127.0.0.1:1883.
set -euo pipefail
BASE=http://localhost:8123
TOKEN=$(cat /home/arduino/.ha_token)
AUTH="Authorization: Bearer $TOKEN"
CT="Content-Type: application/json"
BROKER="${MQTT_BROKER:-127.0.0.1}"
PORT="${MQTT_PORT:-1883}"

resp=$(curl -s --max-time 120 -X POST $BASE/api/config/config_entries/flow \
  -H "$AUTH" -H "$CT" -d '{"handler":"mqtt"}')
echo "step1: $resp"
fid=$(echo "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["flow_id"])')

resp=$(curl -s --max-time 120 -X POST $BASE/api/config/config_entries/flow/$fid \
  -H "$AUTH" -H "$CT" -d "{\"broker\":\"$BROKER\",\"port\":$PORT}")
echo "step2: $resp"
