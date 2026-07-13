#!/bin/bash
# Complete Home Assistant onboarding via REST API and save an access token.
# Run ON THE BOARD (adb shell). Works only on a fresh HA instance: the
# user-creation step fails once onboarding has already been completed.
#
# Env overrides: HA_BASE  (default http://localhost:8123)
#                HA_USER  (default arduino)
#                HA_PASS  (default changeme)
#                HA_TOKEN_FILE (default $HOME/.ha_token)
set -euo pipefail
BASE="${HA_BASE:-http://localhost:8123}"
CID="$BASE/"
USER_NAME="${HA_USER:-arduino}"
PASS="${HA_PASS:-changeme}"
TOKEN_FILE="${HA_TOKEN_FILE:-$HOME/.ha_token}"

status=$(curl -s "$BASE/api/onboarding")
echo "onboarding status: $status"

code=$(curl -s -X POST "$BASE/api/onboarding/users" \
  -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CID\",\"name\":\"$USER_NAME\",\"username\":\"$USER_NAME\",\"password\":\"$PASS\",\"language\":\"en\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["auth_code"])')
echo "got auth_code"

resp=$(curl -s -X POST "$BASE/auth/token" \
  -d "grant_type=authorization_code" -d "code=$code" -d "client_id=$CID")
token=$(echo "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "$token" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
echo "got access token -> $TOKEN_FILE"

curl -s -X POST "$BASE/api/onboarding/core_config" \
  -H "Authorization: Bearer $token" \
  -o /dev/null -w "core_config: %{http_code}\n"
curl -s -X POST "$BASE/api/onboarding/analytics" \
  -H "Authorization: Bearer $token" \
  -o /dev/null -w "analytics: %{http_code}\n"
curl -s -X POST "$BASE/api/onboarding/integration" \
  -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CID\",\"redirect_uri\":\"${CID}?auth_callback=1\"}" \
  -o /dev/null -w "integration: %{http_code}\n"

curl -s "$BASE/api/onboarding"
echo
curl -s "$BASE/api/" -H "Authorization: Bearer $token"
echo
