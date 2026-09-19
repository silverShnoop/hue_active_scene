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

## Cards state facts; Needs you carries the jobs

A card contains information and, at most, an **optional** control — one you
might use, not one you must. Anything the house is asking a person to *do*
is a `sensor.needs_you` row and lives nowhere else.

The reason is not tidiness. A job on a card is a job that can only be
finished by whoever is standing at the panel: the same row in `Needs you`
can be cleared from a phone, from a wall button, or by the thing itself
becoming untrue. Two copies of one job also drift — the card goes on saying
"2 to hang" beside a list that has forgotten them.

So: a count of waiting loads is a fact and belongs on the card. A "Hung"
button is a job and does not.

## ZHA creates no `event` entities. That is ZHA, not a broken device

Every `event.*` in this house comes from the **Hue bridge**. ZHA has no
event platform at all, so a ZHA button fires only `zha_event` and never
gains an entity, however many times it is pressed or re-paired.

Trigger on the event with the device's **IEEE**, which is persistent across
a re-pair in a way `device_id` is not:

```yaml
triggers:
  - trigger: event
    event_type: zha_event
    event_data:
      device_ieee: "20:a7:16:ff:fe:ee:de:45"
      command: remote_button_short_press
```

The eWeLink SNZB-01P gives three distinct commands —
`remote_button_short_press`, `_double_press`, `_long_press`.

## A wet leak sensor says nothing about whether the power is on

The pad stays damp long after the floor has been dealt with, and the cycle
still has to be finished — so power has to be restorable while it is still
wet, and cutting it again has to keep working. Report the two facts
separately and never infer one from the other, in the automation, the
sensor and the card alike.

The leak cutoff is its own tiny automation on purpose: it must stay
readable and must not depend on a custom integration being loaded.

## A restart is not a quick thing here

Home Assistant on this Green takes **five to fifteen minutes** to become
reachable again through the Nabu Casa tunnel after `ha_restart` — and the
restart call itself usually returns a 502, because the connection dies with
the instance. A 502 from the tool is not a failed restart; it is the
restart. Do not re-issue it.

## Known, and deliberately not chased

- Ecovacs authentication fails upstream. Not ours; do not debug it.
- HACS CI is red on repository metadata (no topics). Not from any diff.
- `async_update_device(add_config_entry_id=...)` stops working in Home
  Assistant 2027.8. It is how our sensors sit on core Hue's room devices,
  and the replacements would move core Hue's device to our entry, which is
  hostile. Needs a design decision, not a rename.
