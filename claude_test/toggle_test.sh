#!/bin/bash
# Toggle a HA switch entity on/off at 3-second intervals, verifying the
# reported state after each command. Usage: toggle_test.sh <entity_id> <cycles>
set -euo pipefail
ENTITY="${1:?entity_id}"
CYCLES="${2:-3}"
BASE=http://localhost:8123
TOKEN=$(cat /home/arduino/.ha_token)
AUTH="Authorization: Bearer $TOKEN"
CT="Content-Type: application/json"

get_state() {
  curl -s "$BASE/api/states/$ENTITY" -H "$AUTH" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["state"])'
}

echo "initial state: $(get_state)"
pass=0; fail=0
for i in $(seq 1 "$CYCLES"); do
  for action in turn_on turn_off; do
    curl -s -X POST "$BASE/api/services/switch/$action" -H "$AUTH" -H "$CT" \
      -d "{\"entity_id\":\"$ENTITY\"}" -o /dev/null
    sleep 1
    s=$(get_state)
    want=off; [ "$action" = "turn_on" ] && want=on
    if [ "$s" = "$want" ]; then r=OK; pass=$((pass+1)); else r=MISMATCH; fail=$((fail+1)); fi
    echo "$(date +%H:%M:%S) cycle $i $action -> state=$s [$r]"
    sleep 2
  done
done
echo "final state: $(get_state)"
echo "RESULT: $pass passed, $fail failed"
