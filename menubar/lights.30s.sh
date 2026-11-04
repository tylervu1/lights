#!/bin/bash
# SwiftBar / xbar plugin for the goveed lights server.
# Install: copy into your SwiftBar plugin folder (refreshes every 30s).
API="http://localhost:8777"

STATE=$(curl -s -m 4 "$API/api/state" 2>/dev/null)
if [ -z "$STATE" ]; then
  echo "💡 ·"
  echo "---"
  echo "lights server unreachable | color=gray"
  exit 0
fi

STATE="$STATE" python3 - "$API" <<'PYEOF'
import json, os, sys, urllib.request, urllib.parse

api = sys.argv[1]
s = json.loads(os.environ["STATE"])
devices, rooms = s["devices"], s["rooms"]
on = sum(1 for d in devices if d["power"])
print(f"💡 {on}" if on else "💡")
print("---")

def act(label, target, action, value, indent=""):
    q = urllib.parse.urlencode({"target": target, "action": action, "value": value})
    print(f'{indent}{label} | shell="/usr/bin/curl" param1=-s '
          f'param2="{api}/api/go?{q}" terminal=false refresh=true')

seen, shown = set(), []
for room, names in rooms.items():
    bulbs = [d for d in devices if d["name"].lower() in {n.lower() for n in names}]
    if not bulbs:
        continue
    sig = tuple(sorted(b["id"] for b in bulbs))
    if sig in seen:
        continue
    seen.add(sig)
    shown += [b["id"] for b in bulbs]
    n_on = sum(1 for b in bulbs if b["power"])
    pretty = " ".join(w.capitalize() for w in room.split())
    print(f"{pretty} — {n_on}/{len(bulbs)} on")
    act("Turn on", room, "power", "on", "--")
    act("Turn off", room, "power", "off", "--")
    for pct in (30, 70, 100):
        act(f"{pct}%", room, "brightness", pct, "--")
for d in devices:
    if d["id"] in shown:
        continue
    state = f"{d['brightness']}%" if d["power"] else "off"
    print(f"{d['name']} — {state}")
    act("Turn on", d["name"], "power", "on", "--")
    act("Turn off", d["name"], "power", "off", "--")

print("---")
try:
    with urllib.request.urlopen(api + "/api/presets", timeout=4) as r:
        presets = json.load(r)["presets"]
    if presets:
        print("Presets")
        for name in presets:
            q = urllib.parse.urlencode({"preset": name})
            print(f'--{name} | shell="/usr/bin/curl" param1=-s '
                  f'param2="{api}/api/go?{q}" terminal=false refresh=true')
except Exception:
    pass
print(f"Open app | href={api}")
PYEOF
