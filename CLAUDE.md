# Working on this house

## Live testing

**Test against the Kitchen. Never the Bedroom** — it is in use, and dimming
or re-scening a room someone is sitting in is not a free action.

When a change has to be proven against real bulbs rather than a test
harness:

1. Read the room's state first — the group light, every member bulb, and the
   `sensor.<room>_active_scene` — and write it down.
2. Make the change.
3. Restore all of it, member by member, and re-read to confirm.

A room can also be changed by somebody else while you are working. If the
state you find on the way out is not the state you left, that is a person,
not your leftovers: check before "fixing" it.

## Hue entity ids: bulbs have stolen some room names

The card must target a room's **grouped_light**, not a bulb. In several
rooms a single bulb holds the obvious entity id and the room is suffixed:

| Room | The room (use this) | The bulb (not this) |
| --- | --- | --- |
| Study | `light.study_2` | `light.study` |
| Landing | `light.landing_2` | `light.landing` |
| Gym | `light.gym_2` | `light.gym` — named "Nursery" |
| Anaya's Bedroom | `light.office_2` | `light.office` |

Two reliable tests, and they agree:

- a room or zone entity has an `entity_id` attribute listing its members; a
  bulb has none
- every room and zone with scenes has a `sensor.<room>_active_scene`

`hue_active_scene.set_room_brightness` rejects a bulb outright, which is how
this was found — as a wall of identical error toasts, one per live drag
step.

## Known, and deliberately not chased

- Ecovacs authentication fails upstream. Not ours; do not debug it.
- HACS CI is red on repository metadata (no topics). Not from any diff.
- `async_update_device(add_config_entry_id=...)` stops working in Home
  Assistant 2027.8. It is how our sensors sit on core Hue's room devices,
  and the replacements would move core Hue's device to our entry, which is
  hostile. Needs a design decision, not a rename.
