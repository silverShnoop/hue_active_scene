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

from homeassistant.util import color as color_util, dt as dt_util

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


def timeslots_for_day(api: Any, smart_scene: Any, day: str) -> list[dict[str, Any]]:
    """Resolve one day's timeslots into dashboard-ready dicts.

    Each entry carries its index, start time, target scene name and a hex
    colour derived from that scene's actions.
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
                    "scene": getattr(
                        getattr(scene, "metadata", None), "name", None
                    ),
                    "scene_id": scene_id,
                    "color": scene_color(scene),
                }
            )
        break

    return slots
