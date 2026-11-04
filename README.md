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
- **Energy tracking** — estimated per-bulb consumption integrated from
  state history (no metering hardware needed): daily/weekly/monthly
  totals, cost estimates, 7-day chart, per-room breakdown.
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
```

## Notes

- Initial bulb pairing must happen in the Govee app (Bluetooth); after
  that, `lights refresh` picks up new bulbs.
- Energy numbers are estimates: standby ~0.5 W plus brightness-scaled
  draw (defaults tuned for the 9 W H6008 — adjust `STANDBY_W`/`MAX_W` in
  `goveed.py` for other models). Set `KWH_RATE=` in `config.env` for
  accurate cost math.
- The web server binds to your LAN with no auth — anyone on your network
  can flip your lights. Fine for a home network; don't port-forward it.
