"""Helpers for reading Hue smart scene schedules.

A Hue smart scene — any of them, whatever it is named; "Golden hours" is
simply the one the Hue app ships — holds a weekly schedule: `week_timeslots`
is a list of day groups, each with a `recurrence` (which weekdays it applies
to) and an ordered list of timeslots. Most schedules use a single group
covering all seven days, but a schedule split across several groups (weekdays
and weekend, say) is read the same way. Each timeslot has a start time —
either a clock time or a sunrise/sunset reference — and the id of the regular
scene it switches to.

None of that is exposed by the core Hue integration, so this module resolves
it into plain data a dashboard can draw.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import color as color_util, dt as dt_util

MINUTES_PER_DAY = 24 * 60

_SUN_EVENTS = {"sunrise": SUN_EVENT_SUNRISE, "sunset": SUN_EVENT_SUNSET}

# aiohue's WeekDay enum values are lowercase day names; datetime.weekday() is
# Monday=0. Map one to the other.
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def today_name() -> str:
    """Return today's weekday as the lowercase name aiohue uses.

    Uses Home Assistant's configured time zone, which is what the bridge
    schedules against — not necessarily the host's.
    """
    return _WEEKDAYS[dt_util.now().weekday()]


def _enum_value(value: Any) -> Any:
    """Return `.value` for an enum, or the value itself."""
    return getattr(value, "value", value)


def scene_color(scene: Any) -> str | None:
    """Derive a representative hex colour for a Hue scene.

    Averages the xy colour of every action that carries one, weighted by that
    action's brightness. Falls back to colour temperature if no action sets an
    xy colour, and returns None if the scene carries neither.

    Each action's `color` is an aiohue `ColorFeatureBase` whose `xy` is a
    `ColorPoint` with plain `x`/`y` floats.
    """
    if scene is None:
        return None

    xs: list[float] = []
    ys: list[float] = []
    weights: list[float] = []
    mireks: list[float] = []

    for item in getattr(scene, "actions", []) or []:
        action = getattr(item, "action", None)
        if action is None:
            continue

        dimming = getattr(action, "dimming", None)
        weight = getattr(dimming, "brightness", None) or 100.0

        color = getattr(action, "color", None)
        xy = getattr(color, "xy", None)
        if xy is not None:
            xs.append(xy.x * weight)
            ys.append(xy.y * weight)
            weights.append(weight)
            continue

        ct = getattr(action, "color_temperature", None)
        mirek = getattr(ct, "mirek", None)
        if mirek:
            mireks.append(mirek)

    if weights:
        total = sum(weights)
        rgb = color_util.color_xy_to_RGB(sum(xs) / total, sum(ys) / total)
    elif mireks:
        kelvin = 1_000_000 / (sum(mireks) / len(mireks))
        rgb = color_util.color_temperature_to_rgb(kelvin)
    else:
        return None

    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(rgb[0]))),
        max(0, min(255, int(rgb[1]))),
        max(0, min(255, int(rgb[2]))),
    )


def _start_time(start: Any) -> dict[str, Any]:
    """Normalise a timeslot start into {kind, time} form."""
    kind = _enum_value(getattr(start, "kind", None))
    clock = getattr(start, "time", None)
    if kind != "time" or clock is None:
        # sunrise / sunset — the bridge resolves the actual moment daily and
        # sends a zeroed time object alongside the kind. Keying off `clock`
        # alone turns that into a real-looking 00:00, which a consumer cannot
        # tell apart from a genuine midnight slot.
        return {"kind": kind, "time": None}
    return {
        "kind": kind,
        "time": f"{clock.hour:02d}:{clock.minute:02d}",
    }


def _start_minutes(hass: Any, start: dict[str, Any]) -> int | None:
    """Return a slot's configured start as minutes past local midnight.

    A clock time is taken as given. A sunrise/sunset slot is resolved against
    Home Assistant's own location for today, which is the same calculation the
    bridge makes against its location — close, but not guaranteed identical,
    so treat a resolved time as accurate to a minute or two rather than exact.
    """
    kind = start.get("kind")
    clock = start.get("time")

    if kind == "time":
        if clock is None:
            return None
        hour, _, minute = clock.partition(":")
        return int(hour) * 60 + int(minute)

    event = _SUN_EVENTS.get(kind)
    if event is None or hass is None:
        return None

    moment = get_astral_event_date(hass, event, dt_util.now().date())
    if moment is None:
        # Above the Arctic circle the event can simply not occur on a given
        # day. The bridge has nothing to resolve either, so neither do we.
        return None

    local = dt_util.as_local(moment)
    return local.hour * 60 + local.minute


def _place_on_cycle(slots: list[dict[str, Any]]) -> None:
    """Position each slot on the 24-hour cycle that begins at the first one.

    The bridge runs timeslots in list order, not clock order. That matters
    because the two can disagree: a slot whose clock time falls before the
    slot ahead of it does not move, it collapses to nothing and never runs.
    A schedule ending at 00:00 wraps forward into the next day; a 19:00 slot
    sitting behind a 19:11 sunset does not. From the clock alone those two
    look identical, so each offset is taken modulo the cycle from the first
    slot and then held monotonic, which resolves both the same way the bridge
    does — the wrap moves forward, the overlap collapses to zero.
    """
    if not slots:
        return

    anchor = slots[0]["start_minutes"]
    if anchor is None:
        anchor = next(
            (slot["start_minutes"] for slot in slots
             if slot["start_minutes"] is not None),
            None,
        )
    if anchor is None:
        # Nothing in the day could be resolved; leave the slots unplaced
        # rather than inventing a timeline.
        for slot in slots:
            slot["offset_minutes"] = None
            slot["duration_minutes"] = None
            slot["start_resolved"] = None
        return

    previous = 0
    for slot in slots:
        minutes = slot["start_minutes"]
        offset = (
            previous
            if minutes is None
            else (minutes - anchor) % MINUTES_PER_DAY
        )
        offset = max(offset, previous)
        slot["offset_minutes"] = offset
        slot["start_resolved"] = "{:02d}:{:02d}".format(
            *divmod((anchor + offset) % MINUTES_PER_DAY, 60)
        )
        previous = offset

    for index, slot in enumerate(slots):
        offset = slot["offset_minutes"]

        # Where several slots collapse onto the same moment, the bridge holds
        # the first of them and never runs the rest: a 19:00 slot behind a
        # 19:11 sunset stays dark while the sunset scene runs on to the next
        # real transition. So a slot sharing the offset of the one before it
        # takes no time at all.
        if index and slots[index - 1]["offset_minutes"] == offset:
            slot["duration_minutes"] = 0
            continue

        following = MINUTES_PER_DAY
        for later in slots[index + 1:]:
            if later["offset_minutes"] > offset:
                following = later["offset_minutes"]
                break
        slot["duration_minutes"] = following - offset


def timeslots_for_day(
    hass: Any, api: Any, smart_scene: Any, day: str
) -> list[dict[str, Any]]:
    """Resolve one day's timeslots into dashboard-ready dicts.

    Each entry carries its index, configured start, target scene name and a
    hex colour derived from that scene's actions, plus where it lands on the
    day: `start_resolved` (a real clock time even for sunrise/sunset),
    `offset_minutes` from the start of the cycle, and `duration_minutes`.
    A slot the bridge skips has a duration of zero.
    """
    slots: list[dict[str, Any]] = []

    for group in getattr(smart_scene, "week_timeslots", []) or []:
        recurrence = [_enum_value(d) for d in getattr(group, "recurrence", []) or []]
        if day not in recurrence:
            continue

        for index, slot in enumerate(getattr(group, "timeslots", []) or []):
            target = getattr(slot, "target", None)
            scene_id = getattr(target, "rid", None)
            scene = api.scenes.get(scene_id) if scene_id else None
            start = _start_time(getattr(slot, "start_time", None))
            slots.append(
                {
                    "index": index,
                    "start_kind": start["kind"],
                    "start": start["time"],
                    "start_minutes": _start_minutes(hass, start),
                    "scene": getattr(
                        getattr(scene, "metadata", None), "name", None
                    ),
                    "scene_id": scene_id,
                    "color": scene_color(scene),
                }
            )
        break

    _place_on_cycle(slots)
    for slot in slots:
        # Internal only: the placement above is what consumers need, and a
        # second representation of the same start invites the two to drift.
        del slot["start_minutes"]

    return slots
