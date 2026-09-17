"""Read-only services for inspecting Hue bridge data.

The sensors in this integration report a resolved, dashboard-shaped view of
a smart scene: today's timeslots, in the order the bridge lists them, with
scene names and derived colours. That is the right shape to draw, but it is
the wrong shape to debug with, because a disagreement between what the
bridge holds and what a card renders is invisible once the data has been
through `timeslots_for_day`.

`get_smart_scene` returns the bridge's own view instead: every day group,
every timeslot, in bridge order, with each timeslot's fields exactly as
aiohue received them. Nothing here writes to the bridge.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time
from enum import Enum
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .smart_scene import scene_color, timeslots_for_day, today_name

SERVICE_GET_SMART_SCENE = "get_smart_scene"

ATTR_ENTITY_ID = "entity_id"
ATTR_SCENE_ID = "scene_id"

GET_SMART_SCENE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_SCENE_ID): vol.All(cv.ensure_list, [cv.string]),
    }
)

# Deep enough for the nested resource objects aiohue builds, shallow enough
# that a reference cycle cannot hang the call.
_MAX_DEPTH = 8

_SCHEDULE_SUFFIX = "_schedule"


def _plain(value: Any, depth: int = 0) -> Any:
    """Return `value` as plain, JSON-serialisable data.

    aiohue models are nested dataclasses holding enums, times and further
    dataclasses. Converting them generically rather than field by field is
    the point of this service: it shows what the bridge actually sent,
    including fields this integration does not read today.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if depth >= _MAX_DEPTH:
        return repr(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name, None), depth + 1)
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _plain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item, depth + 1) for item in value]
    return repr(value)


def _bridges(hass: HomeAssistant) -> list[Any]:
    """Return the tracked bridges, or explain why there are none."""
    bridges: list[Any] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        bridges.extend(getattr(entry, "runtime_data", None) or [])

    if not bridges:
        raise ServiceValidationError(
            "Hue Active Scene is not loaded, so no bridge can be read"
        )
    return bridges


def _scene_id_from_unique_id(unique_id: str) -> str | None:
    """Recover a smart scene's bridge id from a schedule sensor's unique id.

    Schedule sensors are registered as `<entry_id>_<scene_id>_schedule`.
    Neither a config entry id nor a Hue resource id contains an underscore,
    so the middle segment comes back whole.
    """
    if not unique_id.endswith(_SCHEDULE_SUFFIX):
        return None
    head = unique_id[: -len(_SCHEDULE_SUFFIX)]
    _, _, scene_id = head.rpartition("_")
    return scene_id or None


def _requested_scene_ids(hass: HomeAssistant, call: ServiceCall) -> set[str] | None:
    """Return the smart scene ids asked for, or None to mean 'all of them'."""
    wanted: set[str] = set(call.data.get(ATTR_SCENE_ID, []))

    entity_ids = call.data.get(ATTR_ENTITY_ID, [])
    if entity_ids:
        ent_reg = er.async_get(hass)
        for entity_id in entity_ids:
            entry = ent_reg.async_get(entity_id)
            if entry is None or entry.platform != DOMAIN:
                raise ServiceValidationError(
                    f"{entity_id} is not a Hue Active Scene entity"
                )
            scene_id = _scene_id_from_unique_id(entry.unique_id)
            if scene_id is None:
                raise ServiceValidationError(
                    f"{entity_id} is not a smart scene schedule sensor"
                )
            wanted.add(scene_id)

    return wanted or None


def _describe_timeslot(api: Any, index: int, slot: Any) -> dict[str, Any]:
    """Describe one timeslot in both resolved and raw form."""
    target = getattr(slot, "target", None)
    scene_id = getattr(target, "rid", None)
    scene = api.scenes.get(scene_id) if scene_id else None
    return {
        # Position in the bridge's own list, not a sorted position. A card
        # that reorders slots by clock time will disagree with this, and
        # that disagreement is what the service exists to make visible.
        "index": index,
        "scene": getattr(getattr(scene, "metadata", None), "name", None),
        "scene_id": scene_id,
        "color": scene_color(scene),
        "raw": _plain(slot),
    }


def _describe_smart_scene(
    hass: HomeAssistant, api: Any, smart_scene: Any
) -> dict[str, Any]:
    """Describe one smart scene as the bridge holds it."""
    group_id = getattr(getattr(smart_scene, "group", None), "rid", None)
    group = api.groups.get(group_id) if group_id else None
    active = getattr(smart_scene, "active_timeslot", None)

    week_timeslots = []
    for group_index, day_group in enumerate(
        getattr(smart_scene, "week_timeslots", []) or []
    ):
        week_timeslots.append(
            {
                "group_index": group_index,
                "recurrence": [
                    _plain(day) for day in getattr(day_group, "recurrence", []) or []
                ],
                "timeslots": [
                    _describe_timeslot(api, index, slot)
                    for index, slot in enumerate(
                        getattr(day_group, "timeslots", []) or []
                    )
                ],
            }
        )

    return {
        "id": smart_scene.id,
        "name": getattr(getattr(smart_scene, "metadata", None), "name", None),
        "state": _plain(getattr(smart_scene, "state", None)),
        "group_id": group_id,
        "group_name": getattr(getattr(group, "metadata", None), "name", None),
        "group_type": _plain(getattr(group, "type", None)),
        "transition_duration": getattr(smart_scene, "transition_duration", None),
        "active_timeslot": _plain(active),
        "week_timeslots": week_timeslots,
        # The same schedule as the sensor renders it, for today only: starts
        # resolved to real clock times and placed on the cycle. Sitting next
        # to the raw week above, it makes a disagreement between the bridge
        # and a dashboard visible in one reading.
        "today_resolved": timeslots_for_day(hass, api, smart_scene, today_name()),
    }


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register this integration's services.

    Called from `async_setup`, so the services exist as soon as the component
    is loaded and are looked up against live config entries per call.
    """

    async def _get_smart_scene(call: ServiceCall) -> ServiceResponse:
        """Return the raw schedule the bridge holds for each smart scene."""
        wanted = _requested_scene_ids(hass, call)
        scenes: list[dict[str, Any]] = []
        seen: set[str] = set()

        for bridge in _bridges(hass):
            api = bridge.api
            for smart_scene in api.scenes.smart_scene:
                if wanted is not None and smart_scene.id not in wanted:
                    continue
                if smart_scene.id in seen:
                    continue
                seen.add(smart_scene.id)
                scenes.append(_describe_smart_scene(hass, api, smart_scene))

        if wanted is not None and (missing := wanted - seen):
            raise ServiceValidationError(
                "No smart scene on any bridge with id " + ", ".join(sorted(missing))
            )

        return {
            # Both are here so a reading can be compared against a sensor's
            # state without having to know when the service was called or
            # which day the bridge thinks it is.
            "generated_at": dt_util.now().isoformat(),
            "today": today_name(),
            "smart_scenes": scenes,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SMART_SCENE,
        _get_smart_scene,
        schema=GET_SMART_SCENE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
