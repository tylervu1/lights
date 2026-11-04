# lights

Self-hosted control for Govee smart bulbs: a terminal CLI plus an
iPhone-friendly web app served from your own machine. Built on Govee's
cloud API, with automatic local LAN control for bulbs that support it.
No dependencies — Python 3 stdlib only.

## Features

- **CLI** — `lights kitchen on`, `lights all 70`, `lights bedroom temp warm`.
  Targets are rooms, name fragments, or `all`; commands hit every matched
  bulb in parallel.
- **Web app** — reactive mobile UI (add to home screen in Safari): room
  cards, brightness/temperature sliders, HSV color wheel, Govee's full
  scene catalog, per-bulb controls. Optimistic updates, so every tap
  responds instantly.
- **Presets** — snapshot every bulb's state and restore it with one tap
  (web UI), `lights preset <name>` (CLI), or a URL. Great for scenes like
  "Movie" or "Cooking" that mix per-room brightness and color.
- **Energy tracking** — estimated per-bulb consumption integrated from
  state history (no metering hardware needed): daily/weekly/monthly
  totals, cost estimates, 7-day/24-hour charts, week-over-week change,
  top-consuming bulb, and a per-room breakdown.
- **Siri / iOS Shortcuts / menu bar** — `GET /api/go` drives everything
  from a plain URL, so a Shortcut, a Siri phrase, or the included SwiftBar
  menu-bar plugin can flip rooms and apply presets.
- **LAN first** — bulbs with LAN Control enabled in the Govee app are
  commanded over local UDP (instant, works without internet); everything
  else goes through the cloud API. The API key never leaves your machine.

## Setup

1. Get an API key: Govee Home app → Profile → Settings → Apply for API Key
   (arrives by email).
2. ```sh
   ./install.sh
   ```
   Installs the CLI to `~/.local/bin/lights`, the server to
   `~/.config/govee/`, and (macOS) a launchd agent that keeps the server
   running at `http://<your-ip>:8777`.
3. Put the key in `~/.config/govee/config.env`, then define room groups
   in `~/.config/govee/rooms.json` (see `rooms.example.json`).
4. On your phone (same wifi): open `http://<your-ip>:8777` in Safari →
   share → Add to Home Screen.

## CLI usage

```
lights                        status of every bulb
lights refresh                re-fetch device list (after adding a bulb)
lights <target> on|off        power
lights <target> <1-100>       brightness percent
lights <target> color <hex|name>
lights <target> temp <2000-9000|warm|neutral|cool>
lights preset                 list saved presets
lights preset <name>          restore a preset
lights preset save <name>     snapshot the current state of every bulb
```

## Siri, Shortcuts & menu bar

`GET /api/go` takes URL parameters so any tool that can open a URL can
control the lights:

```
http://<your-ip>:8777/api/go?preset=movie
http://<your-ip>:8777/api/go?target=kitchen&action=power&value=off
http://<your-ip>:8777/api/go?target=all&action=brightness&value=40
```

- **iOS Shortcuts / Siri** — make a Shortcut with a single "Get Contents
  of URL" action pointing at one of the above, name it (e.g. "Movie
  Night"), and Siri runs it. Chain it into automations (arrive home, time
  of day, etc.).
- **Menu bar (macOS)** — install [SwiftBar](https://swiftbar.app), point
  its plugin folder at `menubar/`, and `lights.30s.sh` adds a menu-bar
  dropdown with per-room toggles, brightness presets, and saved presets.

## Notes

- Initial bulb pairing must happen in the Govee app (Bluetooth); after
  that, `lights refresh` picks up new bulbs.
- Energy numbers are estimates: standby ~0.5 W plus brightness-scaled
  draw (defaults tuned for the 9 W H6008 — adjust `STANDBY_W`/`MAX_W` in
  `goveed.py` for other models). Set `KWH_RATE=` in `config.env` for
  accurate cost math.
- The web server binds to your LAN with no auth — anyone on your network
  can flip your lights. Fine for a home network; don't port-forward it.
