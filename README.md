# Hue Active Scene

**Status:** temporary workaround. Delete this when core PR #151883 ships.
**Created:** 29 August 2026, against Home Assistant 2026.8.3 / aiohue 4.9.0.

## Why this exists

The Hue bridge knows which scene is currently active in each room — that's how
the Hue app highlights the right one. The data reaches Home Assistant over the
bridge's event stream and is parsed by `aiohue`, but the core `hue` integration
throws it away at the entity layer:

- `HueSceneEntity.extra_state_attributes` returns only `group_name`,
  `group_type`, `name`, `speed`, `brightness` and `is_dynamic`. It never reads
  `resource.status`, which holds `active` (`inactive` / `static` /
  `dynamic_palette`) and `last_recall`.
- `HueSmartSceneEntity` *does* expose `is_active`, which is why the Golden hours
  smart scene reports properly while ordinary scenes don't.
- A `scene.*` entity's state is only a last-activated timestamp recorded by Home
  Assistant. It does not update when a scene is recalled from the Hue app or a
  dimmer switch.

`aiohue` 4.9.0 ships `aiohue/v2/scene_activity.py` with a `SceneActivityTracker`
that tracks the active scene per group. Nothing in core uses it yet.

When a Hue bridge entry is reloaded its `runtime_data` — and the API object
underneath — is replaced, so this integration reloads itself whenever a bridge
entry changes state, rather than holding a dead connection.

## What this does

Creates one sensor per Hue room and zone that has scenes:

- **State** — name of the active scene, or `none`
- **Attributes** — `scene_id`, `effective_scene`, `effective_scene_id`,
  `is_smart_scene`, `mode`, `last_recall`, `speed`, `brightness`,
  `group_name`, `group_type`

`effective_scene` matters for smart scenes: while Golden hours is running,
`state` is `Golden hours` and `effective_scene` is the underlying scene the
bridge is currently showing, such as `Shine`.

It also creates one **schedule sensor per smart scene** (Golden hours and
similar natural-light scenes):

- **State** — the scene currently in effect, or `inactive`
- **Attributes** — `timeslots` (today's full schedule: `index`, `start`,
  `start_kind`, `scene`, `scene_id`, `color`), plus `active_index`,
  `is_active`, `weekday`, `transition_duration`, `scene_name`

`start_kind` is `time`, `sunrise` or `sunset`. Sunrise and sunset slots have a
null `start`, because the bridge resolves the actual moment each day and does
not publish it.

`color` is derived, not reported: it averages the xy colour of every action in
the target scene, weighted by that action's brightness, falling back to colour
temperature when no action sets an xy colour. It is a representative colour
for a scene that may use many, so treat it as indicative.

This is what makes a schedule visualisation possible — blobs along a timeline
in each scene's own colour, with the active one highlighted.

Sensors attach to the virtual room/zone device that core Hue already creates, so
they appear alongside that room's lights.

## What it does NOT do

It does not replace, shadow or patch the core `hue` integration. There is no
copy of `homeassistant/components/hue` anywhere. Core Hue upgrades normally and
keeps every fix and feature.

The only coupling is that it reads the Hue config entry's `runtime_data` to
borrow the already-open bridge connection, and imports `SceneActivityTracker`
from the `aiohue` version core already installs. It declares no `requirements`,
so it cannot pin or hold back `aiohue`.

## Install

1. Copy this folder to `config/custom_components/hue_active_scene`
2. Add to `configuration.yaml`:

   ```yaml
   hue_active_scene:
   ```

3. Restart Home Assistant

   The YAML key starts a one-off import flow that creates a config entry; the
   entry is what actually loads the sensors. You can equally skip the YAML and
   add **Hue Active Scene** from Settings → Devices & Services → Add
   Integration. Either way there is nothing to configure, and only one entry is
   allowed.

4. Check Developer Tools → States for `sensor.*_active_scene`

## What could break it

Ordered by likelihood:

1. **`entry.runtime_data` changes shape.** If core Hue stops storing a bridge
   object with an `.api` there, that bridge is skipped; if no usable bridge is
   left the entry retries rather than raising. Verified against Home Assistant
   2026.8.3, where `hue/bridge.py` declares
   `type HueConfigEntry = ConfigEntry[HueBridge]` and assigns
   `self.config_entry.runtime_data = self`.
2. **`aiohue` reorganises `scene_activity`.** A rename or signature change to
   `SceneActivityTracker`, `get_group_state` or `subscribe` breaks the import.
   Watch this on `aiohue` bumps.
3. **Platform setup API changes.** The integration uses the config-entry
   setup path (`async_setup_entry` / `async_forward_entry_setups`), which is
   the direction Home Assistant is standardising on.

If any of these break, you lose these sensors only. Hue itself is unaffected.

## Removing it

Core PR home-assistant/core#151883, "Expose active Hue scene applied to grouped
lights" by sliekens, does this properly upstream. As of 29 August 2026 it is
**open and in draft**. At head commit `84e0139` it wires `SceneActivityTracker`
into `bridge.py` (creating it, calling `start()`, registering `stop` as a reset
job) but nothing consumes it yet — `HueGroupedLight.extra_state_attributes` is
unchanged, so no active-scene attribute is exposed.

When it merges and reaches a release:

1. Check what it exposes and where — expected on the grouped light entity
   (`light.kitchen` and friends), not on scene entities
2. Update the `/bubble-rooms` dashboard scene-tile templates to read it
3. Delete `config/custom_components/hue_active_scene` and the
   `hue_active_scene:` line from `configuration.yaml`
4. Restart

## Dashboard usage

Current scene tiles on `/bubble-rooms` compare `last_changed` timestamps across
a room's scene entities, which only catches activations made through Home
Assistant. Once these sensors exist, switch the `button-card` templates to:

```js
[[[ return states['sensor.kitchen_active_scene'].state === 'Relax'; ]]]
```

That tracks the Hue app and dimmer switches too.
