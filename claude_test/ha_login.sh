#!/bin/bash
# Re-authenticate to HA and store a long-lived token (minted inside the
# homeassistant container, which has aiohttp).
set -euo pipefail
BASE=http://localhost:8123
CID="$BASE/"
PASS="${HA_PASS:?set HA_PASS}"
TOKEN_FILE=/home/arduino/.ha_token

fid=$(curl -s -X POST "$BASE/auth/login_flow" -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CID\",\"handler\":[\"homeassistant\",null],\"redirect_uri\":\"${CID}?auth_callback=1\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["flow_id"])')
code=$(curl -s -X POST "$BASE/auth/login_flow/$fid" -H 'Content-Type: application/json' \
  -d "{\"username\":\"arduino\",\"password\":\"$PASS\",\"client_id\":\"$CID\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"])')
short=$(curl -s -X POST "$BASE/auth/token" \
  -d "grant_type=authorization_code" -d "code=$code" -d "client_id=$CID" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "short-lived token obtained"

docker cp /tmp/mint_ll.py homeassistant:/tmp/mint_ll.py >/dev/null
docker exec -e HA_SHORT_TOKEN="$short" homeassistant python3 /tmp/mint_ll.py > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
echo "long-lived token stored ($(wc -c < "$TOKEN_FILE") bytes)"
curl -s "$BASE/api/" -H "Authorization: Bearer $(cat "$TOKEN_FILE")"; echo
