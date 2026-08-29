#!/usr/bin/env bash
# The hosted detector, with no account and no key.
#
#     bash demos/03_hosted.sh
#
# Everything in 01 and 02 runs locally — `pip install laserbrain` is MIT and runs offline —
# and a demo that only ever runs on your own machine proves nothing about whether the service
# you would pay for is up and correct. This one calls it. There is no Authorization header
# anywhere below, and nothing is stored: POST /v1/check takes the ground in the body.
set -euo pipefail
API="${LASERBRAIN_API:-https://api.phronesis.world}"

one() { python3 -c '
import json, sys
v = json.load(sys.stdin)["verdict"]
print("     {:<12} phi={:.2f}  overlap={:.2f}".format(v["reason"], v["phi"], v["goal_score"]))
print("     " + v["advice"])
'; }

# POST /v1/check is newer than some deployments. Say so plainly rather than letting the
# demo die on a KeyError — a demo whose failure mode is a stack trace teaches the reader
# that the service is broken, when the truth is that this Worker has not been redeployed.
probe=$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' "$API/v1/check" \
        -H 'content-type: application/json' -d '{"ground":"a","goal":"b"}')
if [ "$probe" != "200" ]; then
  echo
  echo "  $API/v1/check answered HTTP $probe, not 200."
  if [ "$probe" = "401" ]; then
    echo "  That is the fall-through to key auth, which means this Worker predates /v1/check"
    echo "  and has not been redeployed yet. The endpoint is not broken; it is not there."
  fi
  echo
  echo "  To run this against a local build instead:"
  echo "      cd workers/laserbrain-mcp-remote && npx wrangler dev --port 8799 --local"
  echo "      LASERBRAIN_API=http://127.0.0.1:8799 bash demos/03_hosted.sh"
  echo
  exit 1
fi

echo
echo "  1. the same errand, reworded"
curl -s --max-time 20 "$API/v1/check" -H 'content-type: application/json' -d '{
  "ground": "write a CSV parser for the import job",
  "goal":   "writing the CSV parser for imports",
  "distance": 3 }' | one

echo
echo "  2. a different errand"
curl -s --max-time 20 "$API/v1/check" -H 'content-type: application/json' -d '{
  "ground": "write a CSV parser for the import job",
  "goal":   "refactor the logging subsystem to structured events" }' | one

echo
echo "  3. a whole run in one call — the slide from 01, scored by the hosted detector"
curl -s --max-time 20 "$API/v1/check" -H 'content-type: application/json' -d '{"steps":[
  {"goal":"fix the failing auth test","distance":8},
  {"goal":"fix the auth test session handling","distance":7},
  {"goal":"refactor session handling for auth","distance":6},
  {"goal":"refactor the session store","distance":6},
  {"goal":"redesign the session store schema","distance":6}]}' | python3 -c '
import json, sys
d = json.load(sys.stdin)
for i, s in enumerate(d["steps"]):
    print("     {}  {:<12} phi={:.2f}  overlap={:.2f}   {}".format(
        i, s["reason"], s["phi"], s["goal_score"], s["goal"]))
print("\n     retained: " + d["retained"])
'
echo
echo "  No key was sent. Nothing was kept. 100 calls a day from one address."
echo "  Reference: https://phronesis.world/laserbrain/api"
echo
