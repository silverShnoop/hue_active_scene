"""Set a Hue room's brightness without turning anything on.

Hue has had a room brightness control all along: every room and zone owns a
`grouped_light` resource with its own `dimming.brightness`, and setting it
sends ONE command to the bridge, which then moves each light in the room
proportionally — the light at a quarter stays a quarter as bright as the one
at full. That is what the slider in the Hue app is driving, which is why it
drags smoothly rather than stepping.

Home Assistant cannot reach it. `light.kitchen` IS that grouped_light, but
the only way to set a brightness through the `light` domain is
`light.turn_on`, and that always asserts `on: true` alongside the dimming —
so dimming a room turns on every bulb a scene deliberately left off.

aiohue's own signature has no such problem:

    async def set_state(self, id, on=None, brightness=None, ...)

`on` defaults to None and is omitted from the payload entirely when it is,
which leaves the off lights off. This module is that one call, exposed as a
service, because this integration already borrows core Hue's bridge
connection and so already holds the controller that makes it.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN, HUE_DOMAIN

SERVICE_SET_ROOM_BRIGHTNESS = "set_room_brightness"

ATTR_ENTITY_ID = "entity_id"
ATTR_BRIGHTNESS_PCT = "brightness_pct"
ATTR_TRANSITION = "transition"

# Hue treats dimming and on/off as separate features, so a brightness of zero
# is not "off" — it is a floor the bridge may reject outright. Turning the
# room off is the power switch's job, and conflating the two here would mean
# a slider dragged to the bottom could not be dragged back up.
MIN_BRIGHTNESS = 1.0
MAX_BRIGHTNESS = 100.0

# Hue's `dynamics.duration` is milliseconds. Seconds is what every other
# Home Assistant transition field takes, so that is what the service takes.
MAX_TRANSITION_S = 60.0

GROUPED_LIGHT = "grouped_light"

SET_ROOM_BRIGHTNESS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_BRIGHTNESS_PCT): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Optional(ATTR_TRANSITION): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=MAX_TRANSITION_S)
        ),
    }
)


def _bridges(hass: HomeAssistant) -> list[Any]:
    """Return the tracked bridges, or explain why there are none."""
    bridges: list[Any] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        bridges.extend(getattr(entry, "runtime_data", None) or [])

    if not bridges:
        raise ServiceValidationError(
            "Hue Active Scene is not loaded, so no bridge can be reached"
        )
    return bridges


def _grouped_light_id(api: Any, resource_id: str) -> str | None:
    """Resolve a Hue resource id to the grouped_light it dims.

    A Hue group light entity's unique id is already the grouped_light's own
    id, so the first lookup answers it. The second path is there because that
    is an implementation detail of the core integration rather than a promise
    it makes: if it ever registers rooms by room id instead, the room names
    its grouped_light among its services and we follow that instead of
    breaking.
    """
    grouped = getattr(api.groups, GROUPED_LIGHT, None)
    if grouped is not None and grouped.get(resource_id) is not None:
        return resource_id

    group = api.groups.get(resource_id)
    for service in getattr(group, "services", []) or []:
        rtype = getattr(getattr(service, "rtype", None), "value", None)
        if rtype == GROUPED_LIGHT:
            return service.rid

    return None


def _resolve(hass: HomeAssistant, entity_id: str) -> tuple[Any, str]:
    """Return the bridge api and grouped_light id behind a Hue light entity."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        raise ServiceValidationError(f"{entity_id} is not a known entity")
    if entry.platform != HUE_DOMAIN:
        raise ServiceValidationError(
            f"{entity_id} is not a Philips Hue entity, so it has no Hue room"
        )

    for bridge in _bridges(hass):
        if (found := _grouped_light_id(bridge.api, entry.unique_id)) is not None:
            return bridge.api, found

    raise ServiceValidationError(
        f"{entity_id} is a Hue light but not a room or zone, so it has no "
        "room brightness to set. Target the room's light, not a single bulb."
    )


@callback
def async_register_room_brightness(hass: HomeAssistant) -> None:
    """Register the room brightness service."""

    async def _set_room_brightness(call: ServiceCall) -> None:
        """Dim every lit light in a room, proportionally, in one command."""
        brightness = min(
            MAX_BRIGHTNESS, max(MIN_BRIGHTNESS, float(call.data[ATTR_BRIGHTNESS_PCT]))
        )
        transition = call.data.get(ATTR_TRANSITION)
        duration = None if transition is None else int(transition * 1000)

        for entity_id in call.data[ATTR_ENTITY_ID]:
            api, grouped_light_id = _resolve(hass, entity_id)
            # `on` is not passed, and so is not sent: the bridge changes the
            # brightness of the lights that are already on and leaves the
            # rest alone. That is the whole point of this service.
            await api.groups.grouped_light.set_state(
                grouped_light_id,
                brightness=brightness,
                transition_time=duration,
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ROOM_BRIGHTNESS,
        _set_room_brightness,
        schema=SET_ROOM_BRIGHTNESS_SCHEMA,
    )
