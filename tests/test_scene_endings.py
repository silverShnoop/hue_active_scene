"""The scene a room lost, and who took it.

Built around what recorder history showed in the Bedroom: the Far light zone
holds one bulb that is also in the Bedroom, recalling the zone's scene ends
the room's, and the room's scene does not come back afterwards.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hue_active_scene.scene_endings import (
    WINDOW,
    SceneEndings,
    group_lights,
)
from custom_components.hue_active_scene.sensor import HueActiveSceneSensor

from .hue_fakes import Group, Scene

BEDROOM = "room-bedroom"
FAR_LIGHT = "zone-far-light"
CASEY = "zone-casey"
KITCHEN = "room-kitchen"
HOME = "zone-home"


class Controller(list):
    """A room or zone controller: its groups, and the lights in each."""

    def __init__(self, groups, lights) -> None:
        super().__init__(groups)
        self._lights = lights

    def get_lights(self, group_id):
        return [SimpleNamespace(id=i) for i in self._lights.get(group_id, [])]


def house():
    """The Bedroom, its two lamp zones, the Kitchen and a whole-house zone."""
    lights = {
        BEDROOM: ["overcuddle", "casey", "overbed"],
        FAR_LIGHT: ["overcuddle"],
        CASEY: ["casey"],
        KITCHEN: ["spot-1", "spot-2"],
        HOME: ["overbed", "spot-1"],
    }
    rooms = Controller([Group(id=BEDROOM, name="Bedroom"),
                        Group(id=KITCHEN, name="Kitchen")], lights)
    zones = Controller([Group(id=FAR_LIGHT, name="Bedroom Far Light", type_="zone"),
                        Group(id=CASEY, name="Casey's lamp", type_="zone"),
                        Group(id=HOME, name="Home", type_="zone")], lights)

    def get(resource_id):
        return next((g for g in [*rooms, *zones] if g.id == resource_id), None)

    groups = SimpleNamespace(room=rooms, zone=zones, get=get)
    scenes = [Scene(id="dimmed", name="Dimmed", group_id=BEDROOM),
              Scene(id="bright", name="Bright", group_id=FAR_LIGHT)]
    return SimpleNamespace(
        groups=groups,
        scenes=SimpleNamespace(
            scene=scenes,
            get=lambda i: next((s for s in scenes if s.id == i), None)),
    )


class Tracker:
    """The scene tracker: what each group is on, and who is listening."""

    def __init__(self) -> None:
        self._scene: dict[str, str | None] = {}
        self._listeners = defaultdict(list)

    def get_group_state(self, group_id):
        return SimpleNamespace(scene_id=self._scene.get(group_id),
                               effective_scene_id=self._scene.get(group_id),
                               scene_mode=None, scene_last_recall=None,
                               scene_speed=None, scene_brightness=None)

    def subscribe(self, group_id, listener):
        self._listeners[group_id].append(listener)
        return lambda: self._listeners[group_id].remove(listener)

    def set(self, group_id, scene_id) -> None:
        self._scene[group_id] = scene_id
        for listener in list(self._listeners[group_id]):
            listener(group_id)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def watching(api, tracker, clock):
    endings = SceneEndings(api, tracker, now=clock)
    endings.start([BEDROOM, FAR_LIGHT, CASEY, KITCHEN, HOME])
    return endings


def test_a_lamp_zone_that_starts_a_scene_is_blamed() -> None:
    """The zone's `static` lands first, then the room loses its scene."""
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(BEDROOM, "dimmed")
    endings = watching(api, tracker, clock)

    tracker.set(FAR_LIGHT, "bright")
    clock.advance(0.03)
    tracker.set(BEDROOM, None)

    ending = endings.ending(BEDROOM)
    assert ending.scene_id == "dimmed"
    assert ending.ended_by == FAR_LIGHT


def test_the_blame_arrives_even_when_the_ending_comes_first() -> None:
    """Nothing promises the order, so an ending waits for its cause."""
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(BEDROOM, "dimmed")
    endings = watching(api, tracker, clock)
    heard = []
    endings.subscribe(BEDROOM, heard.append)

    tracker.set(BEDROOM, None)
    assert endings.ending(BEDROOM).ended_by is None
    clock.advance(0.03)
    tracker.set(FAR_LIGHT, "bright")

    assert endings.ending(BEDROOM).ended_by == FAR_LIGHT
    # The room's sensor has to hear about it, or it goes on saying nobody.
    assert heard == [BEDROOM, BEDROOM]


def test_a_zone_that_shares_no_bulb_is_not_blamed() -> None:
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(KITCHEN, "dimmed")
    endings = watching(api, tracker, clock)

    tracker.set(FAR_LIGHT, "bright")
    tracker.set(KITCHEN, None)

    assert endings.ending(KITCHEN).ended_by is None


def test_a_scene_started_long_before_is_not_blamed() -> None:
    """A lamp switched on a minute before the room went dark did not do it."""
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(BEDROOM, "dimmed")
    endings = watching(api, tracker, clock)

    tracker.set(FAR_LIGHT, "bright")
    clock.advance(WINDOW.total_seconds() + 1)
    tracker.set(BEDROOM, None)

    assert endings.ending(BEDROOM).ended_by is None


def test_recalling_any_scene_forgets_the_old_one() -> None:
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(BEDROOM, "dimmed")
    endings = watching(api, tracker, clock)

    tracker.set(BEDROOM, None)
    clock.advance(30)
    tracker.set(BEDROOM, "dimmed")

    assert endings.ending(BEDROOM) is None


def test_the_room_ending_a_lamps_scene_is_blamed_too() -> None:
    """It runs both ways: a room scene overwrites the lamp."""
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(FAR_LIGHT, "bright")
    endings = watching(api, tracker, clock)

    tracker.set(BEDROOM, "dimmed")
    tracker.set(FAR_LIGHT, None)

    ending = endings.ending(FAR_LIGHT)
    assert ending.scene_id == "bright"
    assert ending.ended_by == BEDROOM


def test_a_zone_with_no_scene_ends_scenes_and_names_nobody() -> None:
    """Dimming the whole-house zone: recorded, never guessed."""
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(BEDROOM, "dimmed")
    tracker.set(KITCHEN, "dimmed")
    endings = watching(api, tracker, clock)

    tracker.set(BEDROOM, None)
    tracker.set(KITCHEN, None)

    assert endings.ending(BEDROOM).ended_by is None
    # And two rooms losing their scenes together do not blame each other,
    # because neither started one.
    assert endings.ending(KITCHEN).ended_by is None


def test_lights_are_read_from_both_rooms_and_zones() -> None:
    api = house()
    assert group_lights(api, BEDROOM) == {"overcuddle", "casey", "overbed"}
    assert group_lights(api, FAR_LIGHT) == {"overcuddle"}
    assert group_lights(api, "nothing") == frozenset()


async def test_the_sensor_says_what_was_lost_and_to_whom(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    api, tracker, clock = house(), Tracker(), Clock()
    tracker.set(BEDROOM, "dimmed")
    endings = watching(api, tracker, clock)
    entity_registry.async_get_or_create(
        "scene", "hue", "dimmed", suggested_object_id="bedroom_dimmed")
    sensor = HueActiveSceneSensor(
        api, tracker, endings, api.groups.get(BEDROOM), "entry", None)
    sensor.hass = hass

    assert sensor.extra_state_attributes["previous_scene"] is None

    tracker.set(FAR_LIGHT, "bright")
    tracker.set(BEDROOM, None)
    attrs = sensor.extra_state_attributes

    assert sensor.native_value == "none"
    assert attrs["previous_scene"] == "Dimmed"
    assert attrs["previous_scene_entity"] == "scene.bedroom_dimmed"
    assert attrs["ended_by"] == "Bedroom Far Light"
    assert attrs["ended_by_id"] == FAR_LIGHT
    assert attrs["scene_ended_at"] == clock.now.isoformat()
