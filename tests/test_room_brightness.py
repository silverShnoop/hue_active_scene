"""The service the dashboard's brightness slider drives.

Home Assistant cannot set a Hue room's brightness without turning the room
on: `light.turn_on` is the only way into the `light` domain's brightness,
and it always asserts `on: true`. So dimming a room through it switches on
every bulb a scene deliberately left off.

This service exists to avoid exactly that, by reaching the `grouped_light`
resource aiohue already holds and omitting `on` from the payload. That
omission is the whole point, so it is what most of this file is about.
"""

from __future__ import annotations

import pytest
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.hue_active_scene.const import DOMAIN
from custom_components.hue_active_scene.room_brightness import (
    MIN_BRIGHTNESS,
    SERVICE_SET_ROOM_BRIGHTNESS,
    SET_ROOM_BRIGHTNESS_SCHEMA,
    _grouped_light_id,
    async_register_room_brightness,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry

from .hue_fakes import Api, Group, Groups, bridge, service

GROUPED_ID = "5f9c8b2a-0000-4000-8000-00000000abcd"
ROOM_ID = "11111111-2222-4333-8444-555555555555"
LIGHT = "light.kitchen"


def _api(direct: bool = True) -> Api:
    """A bridge whose room is dimmable.

    `direct` picks which of the two resolution paths is available: the Hue
    light entity's unique id IS the grouped_light id (what core Hue does
    today), or it is the room's id and the grouped_light has to be found
    among the room's services (what the fallback is for).
    """
    grouped = Group(id=GROUPED_ID, name="Kitchen")
    room = Group(
        id=ROOM_ID,
        name="Kitchen",
        services=[service("grouped_light", GROUPED_ID), service("light", "other")],
    )
    return Api(Groups(rooms=[room], grouped=[grouped] if direct else []))


async def _setup(hass: HomeAssistant, api: Api, unique_id: str = GROUPED_ID) -> None:
    """Register the service with one loaded entry holding one bridge."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = [bridge(api)]

    er.async_get(hass).async_get_or_create(
        "light", "hue", unique_id, suggested_object_id="kitchen"
    )
    async_register_room_brightness(hass)


async def _call(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(
        DOMAIN, SERVICE_SET_ROOM_BRIGHTNESS,
        {"entity_id": LIGHT, **data}, blocking=True,
    )


# --------------------------------------------------------------- the payload

async def test_on_is_never_sent(hass: HomeAssistant) -> None:
    """The reason this service exists.

    aiohue omits `on` from the request body when it is None, and leaving the
    off lights off is the entire difference between this and light.turn_on.
    If `on` ever appears here, a scene's dark bulbs come up with the rest.
    """
    api = _api()
    await _setup(hass, api)
    await _call(hass, brightness_pct=60)

    assert len(api.groups.grouped_light.calls) == 1
    call = api.groups.grouped_light.calls[0]
    assert "on" not in call
    assert call["id"] == GROUPED_ID
    assert call["brightness"] == 60


async def test_transition_is_sent_in_milliseconds(hass: HomeAssistant) -> None:
    """Hue's `dynamics.duration` is ms; every HA transition field is seconds."""
    api = _api()
    await _setup(hass, api)
    await _call(hass, brightness_pct=50, transition=0.2)

    assert api.groups.grouped_light.calls[0]["transition_time"] == 200


async def test_transition_omitted_stays_none(hass: HomeAssistant) -> None:
    """No transition asked for is not a transition of zero."""
    api = _api()
    await _setup(hass, api)
    await _call(hass, brightness_pct=50)

    assert api.groups.grouped_light.calls[0]["transition_time"] is None


# ------------------------------------------------------------- the 0 problem

async def test_zero_becomes_the_floor_not_off(hass: HomeAssistant) -> None:
    """Zero brightness is not "off" to Hue -- it is a floor it may refuse.

    A slider dragged to the bottom has to be draggable back up, so the
    service clamps rather than passing 0 through. Turning the room off is
    the power switch's job.
    """
    api = _api()
    await _setup(hass, api)
    await _call(hass, brightness_pct=0)

    call = api.groups.grouped_light.calls[0]
    assert call["brightness"] == MIN_BRIGHTNESS
    assert "on" not in call


@pytest.mark.parametrize(("asked", "sent"), [(1, 1.0), (50, 50.0), (100, 100.0)])
async def test_values_in_range_pass_through(
    hass: HomeAssistant, asked: int, sent: float
) -> None:
    """Clamping must not disturb anything that was already valid."""
    api = _api()
    await _setup(hass, api)
    await _call(hass, brightness_pct=asked)

    assert api.groups.grouped_light.calls[0]["brightness"] == sent


# ------------------------------------------------------------- the schema

@pytest.mark.parametrize("bad", [-1, 101, "bright"])
def test_schema_rejects_impossible_brightness(bad) -> None:
    with pytest.raises(vol.Invalid):
        SET_ROOM_BRIGHTNESS_SCHEMA(
            {"entity_id": [LIGHT], "brightness_pct": bad}
        )


def test_schema_rejects_an_absurd_transition() -> None:
    """A slider that fades for an hour is a bug, not a preference."""
    with pytest.raises(vol.Invalid):
        SET_ROOM_BRIGHTNESS_SCHEMA(
            {"entity_id": [LIGHT], "brightness_pct": 50, "transition": 3600}
        )


def test_schema_requires_a_brightness() -> None:
    with pytest.raises(vol.Invalid):
        SET_ROOM_BRIGHTNESS_SCHEMA({"entity_id": [LIGHT]})


# ------------------------------------------------- finding the grouped_light

def test_grouped_light_found_directly() -> None:
    """Core Hue registers a room's light under the grouped_light's own id."""
    api = _api()
    assert _grouped_light_id(api, GROUPED_ID) == GROUPED_ID


def test_grouped_light_found_through_the_rooms_services() -> None:
    """The fallback, for if core Hue ever keys rooms by room id instead.

    That it does not today is an implementation detail of another
    integration, not a promise it makes to this one.
    """
    api = _api(direct=False)
    assert _grouped_light_id(api, ROOM_ID) == GROUPED_ID


def test_grouped_light_not_found_is_none_not_a_guess() -> None:
    api = _api()
    assert _grouped_light_id(api, "no-such-resource") is None


# ------------------------------------------------------------- what goes wrong

async def test_unknown_entity_is_explained(hass: HomeAssistant) -> None:
    api = _api()
    await _setup(hass, api)
    with pytest.raises(ServiceValidationError, match="not a known entity"):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_ROOM_BRIGHTNESS,
            {"entity_id": "light.nonexistent", "brightness_pct": 50}, blocking=True,
        )
    assert not api.groups.grouped_light.calls


async def test_a_non_hue_light_is_explained(hass: HomeAssistant) -> None:
    api = _api()
    await _setup(hass, api)
    er.async_get(hass).async_get_or_create(
        "light", "tplink", "abc", suggested_object_id="lamp"
    )
    with pytest.raises(ServiceValidationError, match="not a Philips Hue entity"):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_ROOM_BRIGHTNESS,
            {"entity_id": "light.lamp", "brightness_pct": 50}, blocking=True,
        )
    assert not api.groups.grouped_light.calls


async def test_a_single_bulb_is_explained(hass: HomeAssistant) -> None:
    """A Hue light that is not a room has no room brightness to set.

    The message has to say so usefully: this is the mistake a dashboard
    author will actually make.
    """
    api = _api()
    await _setup(hass, api, unique_id="a-single-bulb")
    with pytest.raises(ServiceValidationError, match="Target the room's light"):
        await _call(hass, brightness_pct=50)
    assert not api.groups.grouped_light.calls


async def test_no_loaded_bridge_is_explained(hass: HomeAssistant) -> None:
    """Registered but with nothing behind it, which is a startup ordering bug
    rather than a user error, so it must not fail silently."""
    er.async_get(hass).async_get_or_create(
        "light", "hue", GROUPED_ID, suggested_object_id="kitchen"
    )
    async_register_room_brightness(hass)
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await _call(hass, brightness_pct=50)
