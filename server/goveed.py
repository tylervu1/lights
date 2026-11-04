#!/usr/bin/env python3
"""Local web UI for Govee bulbs. Serves on 0.0.0.0:8777.

Reads the same config as the `lights` CLI:
  ~/.config/govee/config.env   GOVEE_API_KEY=...
  ~/.config/govee/rooms.json   {"room": ["Bulb Name", ...]}
UI lives in webui.html next to this file.
"""

import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF_DIR = os.path.dirname(os.path.abspath(__file__))
API = "https://openapi.api.govee.com/router/api/v1"
CACHE = os.path.join(CONF_DIR, "devices-cache.json")
SCENES_CACHE = os.path.join(CONF_DIR, "scenes-cache.json")
PORT = 8777


def api_key():
    with open(os.path.join(CONF_DIR, "config.env")) as f:
        for line in f:
            if line.strip().startswith("GOVEE_API_KEY="):
                return line.strip().split("=", 1)[1]
    sys.exit("no GOVEE_API_KEY in config.env")


KEY = api_key()

# ---- energy model (H6008: ~9 W at full brightness, ~0.5 W wifi standby) ----
ENERGY_FILE = os.path.join(CONF_DIR, "energy.json")
STANDBY_W = 0.5
MAX_W = 9.0


def kwh_rate():
    try:
        with open(os.path.join(CONF_DIR, "config.env")) as f:
            for line in f:
                if line.strip().startswith("KWH_RATE="):
                    return float(line.strip().split("=", 1)[1])
    except (OSError, ValueError):
        pass
    return 0.30  # $/kWh default; set KWH_RATE= in config.env to override


RATE = kwh_rate()


def api_call(path, body=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body else None,
        headers={"Govee-API-Key": KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def get_devices(force=False):
    if not force:
        try:
            if time.time() - os.stat(CACHE).st_mtime < 86400:
                with open(CACHE) as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    devices = api_call("/user/devices")["data"]
    with open(CACHE, "w") as f:
        json.dump(devices, f)
    return devices


def load_rooms():
    try:
        with open(os.path.join(CONF_DIR, "rooms.json")) as f:
            rooms = json.load(f)
        return {k: v for k, v in rooms.items() if not k.startswith("_")}
    except (OSError, json.JSONDecodeError):
        return {}


# ---- scenes (per SKU; Govee scene ids are shared across same-model bulbs) --

_scenes_lock = threading.Lock()


def get_scenes(sku, device, force=False):
    with _scenes_lock:
        cache = {}
        try:
            with open(SCENES_CACHE) as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        hit = cache.get(sku)
        if hit and not force and time.time() - hit["at"] < 7 * 86400:
            return hit["scenes"]
        scenes = []
        for path, instance in (("/device/scenes", "lightScene"),
                               ("/device/diy-scenes", "diyScene")):
            try:
                data = api_call(path, {
                    "requestId": str(uuid.uuid4()),
                    "payload": {"sku": sku, "device": device},
                })
                for cap in data.get("payload", {}).get("capabilities", []):
                    for opt in cap.get("parameters", {}).get("options", []):
                        scenes.append({"name": opt["name"],
                                       "value": opt["value"],
                                       "instance": instance})
            except Exception:
                continue
        cache[sku] = {"at": time.time(), "scenes": scenes}
        with open(SCENES_CACHE, "w") as f:
            json.dump(cache, f)
        return scenes


# ---- LAN control (used automatically when a bulb has LAN Control on) ----

_lan = {"ips": {}, "at": 0.0, "lock": threading.Lock()}


def lan_ips():
    with _lan["lock"]:
        if time.time() - _lan["at"] < 60:
            return _lan["ips"]
        found = {}
        try:
            recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            recv.bind(("0.0.0.0", 4002))
            recv.settimeout(0.3)
            send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            send.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            msg = json.dumps({"msg": {"cmd": "scan",
                                      "data": {"account_topic": "reserve"}}})
            send.sendto(msg.encode(), ("239.255.255.250", 4001))
            deadline = time.time() + 1.2
            while time.time() < deadline:
                try:
                    data, _ = recv.recvfrom(4096)
                    m = json.loads(data.decode())["msg"]
                    if m.get("cmd") == "scan":
                        found[m["data"]["device"]] = m["data"]["ip"]
                except (socket.timeout, ValueError, KeyError):
                    continue
            recv.close()
        except OSError:
            pass
        _lan["ips"], _lan["at"] = found, time.time()
        return found


def lan_send(ip, cmd, data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(json.dumps({"msg": {"cmd": cmd, "data": data}}).encode(),
             (ip, 4003))


# ---- energy tracking ----
# Believed per-bulb state: updated instantly by every control command and
# reconciled against the cloud every 5 min; integrated into hourly Wh bins.

_energy_lock = threading.Lock()
_believed = {}  # device_id -> {"power", "brightness", "online"}


def update_believed(states):
    for s in states:
        if "error" not in s:
            _believed[s["id"]] = {"power": s["power"],
                                  "brightness": s["brightness"],
                                  "online": s["online"]}


def believed_apply_control(devs, action, value):
    for d in devs:
        b = _believed.setdefault(d["device"],
                                 {"power": None, "brightness": None,
                                  "online": True})
        if action == "power":
            b["power"] = bool(value)
        elif action == "brightness":
            b["brightness"] = int(value)
            b["power"] = True
        elif action in ("temp", "color", "scene"):
            b["power"] = True


def watts_of(b):
    # Govee's "online" flag is flaky (bulbs report offline while happily
    # executing commands), so a reported power=on always counts.
    if b.get("power"):
        return STANDBY_W + ((b.get("brightness") or 100) / 100) * (MAX_W - STANDBY_W)
    if b.get("online") is False:
        return 0.0  # off and unreachable: likely no mains power
    if b.get("power") is False:
        return STANDBY_W
    return None  # state never observed yet


def _load_energy():
    try:
        with open(ENERGY_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def energy_loop():
    last = time.time()
    last_poll = 0.0
    while True:
        time.sleep(60)
        now = time.time()
        dt, last = now - last, now
        if now - last_poll > 300:
            try:
                devices = get_devices()
                ips = lan_ips()
                with ThreadPoolExecutor(max_workers=max(1, len(devices))) as ex:
                    update_believed(list(ex.map(lambda d: state_one(d, ips),
                                                devices)))
                last_poll = now
            except Exception:
                pass
        with _energy_lock:
            data = _load_energy()
            hour = time.strftime("%Y-%m-%dT%H")
            bin_ = data.setdefault(hour, {})
            for dev_id, b in _believed.items():
                w = watts_of(b)
                if w is not None:
                    bin_[dev_id] = round(bin_.get(dev_id, 0) + w * dt / 3600, 4)
            cut = time.strftime("%Y-%m-%dT%H", time.localtime(now - 60 * 86400))
            data = {k: v for k, v in data.items() if k >= cut}
            try:
                with open(ENERGY_FILE, "w") as f:
                    json.dump(data, f)
            except OSError:
                pass


def energy_summary():
    with _energy_lock:
        data = _load_energy()
    try:
        names = {d["device"]: d["deviceName"] for d in get_devices()}
    except Exception:
        names = {}
    daily = {}
    for hour, devs in data.items():
        db = daily.setdefault(hour[:10], {})
        for dev, wh in devs.items():
            db[dev] = db.get(dev, 0) + wh
    days = []
    for i in range(6, -1, -1):
        date = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        days.append({"date": date,
                     "wh": round(sum(daily.get(date, {}).values()), 2)})

    def tot(dates):
        out = {}
        for dt_ in dates:
            for dev, wh in daily.get(dt_, {}).items():
                out[dev] = out.get(dev, 0) + wh
        return out

    month_dates = [time.strftime("%Y-%m-%d",
                                 time.localtime(time.time() - i * 86400))
                   for i in range(30)]
    tt = daily.get(time.strftime("%Y-%m-%d"), {})
    tw = tot(d["date"] for d in days)
    tm = tot(month_dates)
    per_bulb = {dev: {"name": names.get(dev, dev),
                      "today_wh": round(tt.get(dev, 0), 2),
                      "week_wh": round(tw.get(dev, 0), 2),
                      "month_wh": round(tm.get(dev, 0), 2)}
                for dev in names}
    return {"rate": RATE,
            "today_wh": round(sum(tt.values()), 2),
            "week_wh": round(sum(tw.values()), 2),
            "month_wh": round(sum(tm.values()), 2),
            "days": days, "per_bulb": per_bulb,
            "since": min(data) if data else None}


# ---- command plumbing ----

def make_plan(action, value):
    """Return (cloud_capability, cloud_value, lan_cmd, lan_data)."""
    if action == "power":
        v = 1 if value else 0
        return ({"type": "devices.capabilities.on_off",
                 "instance": "powerSwitch"}, v, "turn", {"value": v})
    if action == "brightness":
        v = max(1, min(100, int(value)))
        return ({"type": "devices.capabilities.range",
                 "instance": "brightness"}, v, "brightness", {"value": v})
    if action == "temp":
        k = max(2000, min(9000, int(value)))
        return ({"type": "devices.capabilities.color_setting",
                 "instance": "colorTemperatureK"}, k,
                "colorwc", {"colorTemInKelvin": k})
    if action == "color":
        rgb = int(str(value).lstrip("#"), 16)
        return ({"type": "devices.capabilities.color_setting",
                 "instance": "colorRgb"}, rgb,
                "colorwc", {"color": {"r": rgb >> 16, "g": (rgb >> 8) & 0xFF,
                                      "b": rgb & 0xFF}})
    if action == "scene":
        # value: {"value": <govee scene value>, "instance": lightScene|diyScene}
        return ({"type": "devices.capabilities.dynamic_scene",
                 "instance": value["instance"]}, value["value"], None, None)
    raise ValueError(f"unknown action {action}")


def control_one(dev, plan, ips):
    cap, value, lan_cmd, lan_data = plan
    ip = ips.get(dev["device"])
    if ip and lan_cmd:
        lan_send(ip, lan_cmd, lan_data)
        return "lan"
    api_call("/device/control", {
        "requestId": str(uuid.uuid4()),
        "payload": {"sku": dev["sku"], "device": dev["device"],
                    "capability": cap | {"value": value}},
    })
    return "cloud"


def pick(devices, target):
    if target == "all":
        return devices
    rooms = {k.lower(): v for k, v in load_rooms().items()}
    if target.lower() in rooms:
        names = {n.lower() for n in rooms[target.lower()]}
        return [d for d in devices if d["deviceName"].lower() in names]
    return [d for d in devices
            if d["deviceName"].lower() == target.lower()]


def state_one(dev, ips):
    out = {"name": dev["deviceName"], "id": dev["device"], "sku": dev["sku"],
           "lan": dev["device"] in ips, "power": None, "brightness": None,
           "online": None, "tempK": None, "colorRgb": None}
    try:
        caps = api_call("/device/state", {
            "requestId": str(uuid.uuid4()),
            "payload": {"sku": dev["sku"], "device": dev["device"]},
        })["payload"]["capabilities"]
        for c in caps:
            v = c.get("state", {}).get("value")
            inst = c.get("instance")
            if inst == "powerSwitch":
                out["power"] = v == 1
            elif inst == "brightness":
                out["brightness"] = v
            elif inst == "colorTemperatureK":
                out["tempK"] = v or None
            elif inst == "colorRgb":
                out["colorRgb"] = v
            elif inst == "online":
                out["online"] = bool(v) if isinstance(v, bool) else v != "false"
    except Exception as e:
        out["error"] = str(e)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ("/", "/index.html"):
            try:
                with open(os.path.join(CONF_DIR, "webui.html"), "rb") as f:
                    body = f.read()
            except OSError:
                self.send_error(500, "webui.html missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/state":
            force = "refresh" in url.query
            devices = get_devices(force=force)
            ips = lan_ips()
            with ThreadPoolExecutor(max_workers=max(1, len(devices))) as ex:
                states = list(ex.map(lambda d: state_one(d, ips), devices))
            update_believed(states)
            self._json({"rooms": load_rooms(), "devices": states})
        elif url.path == "/api/energy":
            self._json(energy_summary())
        elif url.path == "/api/scenes":
            q = urllib.parse.parse_qs(url.query)
            try:
                sku, device = q["sku"][0], q["device"][0]
            except KeyError:
                self._json({"error": "need sku and device"}, 400)
                return
            self._json({"scenes": get_scenes(sku, device,
                                             force="refresh" in url.query)})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/control":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            plan = make_plan(req["action"], req.get("value"))
            devices = pick(get_devices(), req["target"])
            if not devices:
                self._json({"error": f"no match for {req['target']}"}, 404)
                return
            ips = lan_ips()
            believed_apply_control(devices, req["action"], req.get("value"))
            with ThreadPoolExecutor(max_workers=len(devices)) as ex:
                results = list(ex.map(
                    lambda d: {"name": d["deviceName"],
                               "via": control_one(d, plan, ips)}, devices))
            self._json({"ok": True, "results": results})
        except Exception as e:
            self._json({"error": str(e)}, 500)


if __name__ == "__main__":
    threading.Thread(target=energy_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"goveed listening on :{PORT}")
    srv.serve_forever()
