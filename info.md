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

Add to `configuration.yaml`, then restart:

```yaml
hue_active_scene:
```
