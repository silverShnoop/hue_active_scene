# Hue Active Scene

Reports which Philips Hue scene is currently active in each room or zone, and
resolves the daily schedule behind smart scenes such as Golden hours.

Sits alongside the core Hue integration — it does not replace, shadow or patch
it. It borrows the bridge connection Home Assistant already holds.

## Sensors

- `sensor.<room>_active_scene` — the scene active in that room, with the
  underlying scene when a smart scene is running
- `sensor.<room>_<smart scene>_schedule` — today's timeslots, each with a start
  time, target scene and derived colour

## Setup

Add **Hue Active Scene** from Settings → Devices & Services → Add Integration,
or add this to `configuration.yaml` and restart:

```yaml
hue_active_scene:
```

There is nothing to configure — it picks up every Hue V2 bridge Home Assistant
already has set up.
