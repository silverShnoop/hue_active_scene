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

## Yellow, orange and red belong to the levels. Nothing else may wear them

A job has a **level**, and the level is a promise about a timeline:

| Level | The promise | Card treatment |
| --- | --- | --- |
| `attention` | needs doing today or tomorrow. Real, but it keeps. | 2px border |
| `waiting` | something is paused or degrading until a person acts | border + 1px inset ring |
| `critical` | damage or risk is accruing now | ring + soft ground |

The name is the test a new row has to pass. Before there were three,
ten of the twelve rows were the same "warning" whatever they meant, and
the two that were not spent the loudest colour in the house on a chore
and on thirty-one entities that had gone quiet.

**A level is a three-way obligation, and it is all three or none.** It
colours the card, it colours that tab's rail button, and it creates a
`sensor.needs_you` row. A card that goes yellow without a row is a job
nobody can clear from a phone; a row with no card is a job with nowhere
to look; a card and a row with a quiet rail button is a tab you only
find by opening it.

**A thing that needs no doing takes no level.** Not the quietest one —
none. An open appliance door, seven pending updates, a night that has
already happened: those are facts, they live on a card, and they wear a
decorative accent. Yellow on a morning with nothing wrong is how a
yellow stops meaning anything.

### The two palettes

`accent` is decorative and says only which tab a card belongs to.
`outline` is a level. They used to be the same six numbers, which is how
a card came to claim an alarm by naming a hue — and how repainting a
decorative slot would silently have repainted the leak on the washer.

The decorative six are **brown (a1, Climate), bone (a2, Lights), moss,
teal, slate, plum**. Climate and Lights kept their slot numbers, so the
two hues moved out of the palette without either dashboard being
rewritten.

**Weight carries the step as well as hue.** Yellow and orange measure ΔE
13.3 apart to normal vision, under the 15 floor, and across a kitchen at
an angle that is not a difference. The ring and the fill survive the
distance and colour-blindness; the hue step alone does not.

**Home never wears a level.** It surfaces cards whose detail lives on
another tab, so a row raised by a card shown there colours the tab that
owns it — Bins on Cleaning, Who's home on Security.

### There is no brown in dark mode

Brown *is* a dark orange — darkness is the whole of what makes it brown
— and a dark ground takes that away. Lifted honestly it becomes a tan,
which measures deutan ΔE **1.0** from the orange level: the same colour
to a red-green-blind reader. So Climate's dark accent is a taupe
instead, trading hue for chroma, which leaves it ΔE 6.5 from
`--sp-ink-3`.

That is close, and it was chosen knowingly: ink is a different *position*
on the card — body text, never a tick — whereas the orange level would be
a different *meaning* in the same glance.

A tab accent has to keep its **role** across themes, not its hue. If the
taupe proves too quiet in practice, the fix is a different hue in dark,
not a brighter tan.

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
      command: toggle
```

**Capture the command; do not read it off the datasheet.** This entry used
to say the eWeLink SNZB-01P gives `remote_button_short_press`,
`_double_press` and `_long_press`. It does not — not this one. The laundry
button was written against those names and fired **zero** times in two
days, silently, because nothing in Home Assistant complains about a trigger
that never matches.

It reports on the **On/Off cluster (0x0006)** rather than emitting parsed
button commands, so its gestures arrive as that cluster's commands:

| Gesture | `command` | |
| --- | --- | --- |
| short press | `toggle` | seen twice, and the automation fired on it |
| long press / double tap | `off` and `on` | **which is which is not known** |

That second row is the trap, and it is worth being exact about. A capture
tells you which commands a device *can* send. It does **not** tell you
which gesture sent them — the event carries no gesture information at all.
Pressing short, then long, then double and lining the three events up
against that order is reading your own typing back, not evidence.

To attribute a gesture, repeat **one** gesture three times with a pause
between each. Three identical commands identify it whatever order anything
was done in.

The laundry button is short-press only for exactly this reason: a
clear-every-load was not worth putting on a coin flip between the two
gestures easiest to do by accident.

Some gestures also emit an `attribute_updated` for `on_off` alongside the
command. Do not trigger on it: it only fires when the value actually
changes, so it is missing on a repeat, and its order relative to the
command varies. The commands carry no `args`.

**A command can arrive twice for one press.** If the button misses the
coordinator's ack it retransmits, and ZHA fires a second, identical
`zha_event` about a millisecond later. The laundry button did exactly this
and, under `mode: queued`, cleared two loads for one press. A button
automation that changes a count must debounce: `mode: single`,
`max_exceeded: silent`, and a short `delay` (250 ms) after the action so the
duplicate lands while the first run is still holding.

Whether a device is parsed into `remote_button_*` names depends on a ZHA
quirk existing for it, so the same model can behave either way — which is
exactly why the answer has to be read off the device rather than assumed.
To capture it: Tools → Events, subscribe to `zha_event`, press the button.
Or, without a browser, a throwaway automation triggering on `zha_event`
with **no filter at all** — unfiltered on purpose, because a device
re-paired under a different IEEE is precisely the case a filtered capture
would miss.

## A wet leak sensor says nothing about whether the power is on

Report the two facts separately and never infer one from the other — in the
sensor and on the card alike. The pad stays damp long after the floor has
been dealt with, so "wet" must never be rendered as "off".

Wet is reported. It is **not** a lock on the plug. A version of this cut the
power again whenever the plug was switched on while the pad was still wet,
with an override helper to escape it, and that was wrong twice over: the
wash still has to be finished on a pad that has not dried, and a control
that gets silently undone a second later is worse than no control at all.
Somebody switching the plug back on has decided to. We trust them to have
looked at the floor.

So the cutoff fires on one thing only: the pad **going** wet, which is new
information every time it happens. Nothing else, and nothing ever switches
the plug back on.

The same rule reaches the card. The emergency stop offers Cut or Restore
purely from `switch.washing_machine_plug`, read straight from the switch
rather than through the integration's copy of it — so the one control that
matters in an emergency still tells the truth while `home_signals` is
reloading, and so no other fact on the card can change which button you get.

The leak cutoff is its own tiny automation on purpose: it must stay readable
and must not depend on a custom integration being loaded.

## HACS will silently install `main` instead of your branch

`ha_manage_hacs(action="download", version="<sha>")` only fetches that
commit if it is **reachable from the default branch**. Give it a sha that
lives only on a side branch and it records your string as
`installed_version` while actually downloading `main` — no error, no
warning, and the entity you were expecting simply never appears.

Tell the two apart with `ha_get_hacs_info(action="info", ...)` and read
`ref`:

- `ref: "tags/<sha>"` — it really fetched that commit
- `ref: "main"` — it fell back, and whatever you think you deployed is not
  on the machine

So a branch build cannot be tested on the panel. It has to be merged
first.

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
