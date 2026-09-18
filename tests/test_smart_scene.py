"""Reading a Hue room: its scenes, their colours, and its schedule.

Core Hue gives a dashboard a `scene.*` entity per scene and nothing else --
no colour, and no way to tell a scene the schedule already drives from one
it does not. A card offering "everything this room can be, apart from what
the schedule handles" needs both, which is what this module works out.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hue_active_scene.smart_scene import (
    _place_on_cycle,
    room_scenes,
    scene_color,
    scheduled_scene_ids,
)

from .hue_fakes import (
    Api,
    Group,
    Groups,
    Scene,
    Scenes,
    SmartScene,
    action,
    day_group,
    timeslot,
)

KITCHEN = "kitchen-group-id"
BEDROOM = "bedroom-group-id"


# ------------------------------------------------- which scenes are scheduled

def test_a_scene_scheduled_only_at_weekends_still_counts() -> None:
    """The whole week, not just today.

    A scene that runs on Saturdays is a scheduled scene on a Tuesday too. A
    card offering it as an off-schedule choice would be wrong twice over: it
    is on the schedule, and picking it gets overridden when Saturday comes.
    """
    smart = SmartScene(id="smart-1", group_id=KITCHEN, week=[
        day_group(["monday"], [timeslot("weekday-scene", 7, 0)]),
        day_group(["saturday", "sunday"], [timeslot("weekend-scene", 9, 30)]),
    ])
    api = Api(Groups(), Scenes(smart=[smart]))

    assert scheduled_scene_ids(api, KITCHEN) == {"weekday-scene", "weekend-scene"}


def test_another_rooms_schedule_is_not_this_rooms() -> None:
    """Two rooms can schedule scenes with the same name, and often do --
    every Hue room ships a "Relax". Filtering has to be by group."""
    mine = SmartScene(id="s1", group_id=KITCHEN,
                      week=[day_group(["monday"], [timeslot("kitchen-relax")])])
    theirs = SmartScene(id="s2", group_id=BEDROOM,
                        week=[day_group(["monday"], [timeslot("bedroom-relax")])])
    api = Api(Groups(), Scenes(smart=[mine, theirs]))

    assert scheduled_scene_ids(api, KITCHEN) == {"kitchen-relax"}
    assert scheduled_scene_ids(api, BEDROOM) == {"bedroom-relax"}


def test_a_room_with_no_schedule_schedules_nothing() -> None:
    assert scheduled_scene_ids(Api(Groups(), Scenes()), KITCHEN) == set()


# ------------------------------------------------------------ describing them

async def test_room_scenes_reports_what_a_card_needs(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Name, entity, colour and whether the schedule drives it.

    The entity id is here because a card that offers a scene has to be able
    to turn it on, and `scene.turn_on` wants the Home Assistant entity, not
    the bridge's id. Only the registry knows which is which, and a card
    cannot read the registry.
    """
    warm = Scene(id="scene-relax", name="Relax", group_id=KITCHEN,
                 actions=[action(x=0.5, y=0.4, brightness=80)])
    cool = Scene(id="scene-bright", name="Bright", group_id=KITCHEN,
                 actions=[action(x=0.32, y=0.33, brightness=100)])
    smart = SmartScene(id="smart-1", group_id=KITCHEN,
                       week=[day_group(["monday"], [timeslot("scene-bright")])])
    api = Api(Groups(rooms=[Group(id=KITCHEN)]),
              Scenes(scenes=[warm, cool], smart=[smart]))

    entity_registry.async_get_or_create(
        "scene", "hue", "scene-relax", suggested_object_id="kitchen_relax")

    found = room_scenes(hass, api, KITCHEN)
    by_name = {s["name"]: s for s in found}

    assert by_name["Relax"]["entity_id"] == "scene.kitchen_relax"
    assert by_name["Relax"]["scheduled"] is False
    assert by_name["Relax"]["color"].startswith("#")
    assert by_name["Bright"]["scheduled"] is True
    # Not registered as an entity, which a card must be able to notice rather
    # than be handed a plausible-looking guess.
    assert by_name["Bright"]["entity_id"] is None


async def test_room_scenes_are_sorted_by_name_not_by_the_bridge(
    hass: HomeAssistant,
) -> None:
    """The bridge's order is not stable across restarts; a row of bands that
    reshuffles itself is worse than one in an arbitrary but fixed order."""
    api = Api(Groups(rooms=[Group(id=KITCHEN)]), Scenes(scenes=[
        Scene(id="c", name="rest", group_id=KITCHEN),
        Scene(id="a", name="Bright", group_id=KITCHEN),
        Scene(id="b", name="concentrate", group_id=KITCHEN),
    ]))

    assert [s["name"] for s in room_scenes(hass, api, KITCHEN)] == [
        "Bright", "concentrate", "rest",
    ]


async def test_room_scenes_ignores_other_rooms(hass: HomeAssistant) -> None:
    api = Api(Groups(rooms=[Group(id=KITCHEN)]), Scenes(scenes=[
        Scene(id="a", name="Mine", group_id=KITCHEN),
        Scene(id="b", name="Theirs", group_id=BEDROOM),
    ]))

    assert [s["name"] for s in room_scenes(hass, api, KITCHEN)] == ["Mine"]


# ------------------------------------------------------------------- colour

def test_colour_is_weighted_by_how_bright_each_light_is() -> None:
    """A scene is what it looks like, and a bulb at 5% contributes almost
    nothing to that however saturated it is."""
    dominant = Scene(id="s", name="S", group_id=KITCHEN, actions=[
        action(x=0.60, y=0.35, brightness=100),
        action(x=0.20, y=0.20, brightness=1),
    ])
    even = Scene(id="s2", name="S2", group_id=KITCHEN, actions=[
        action(x=0.60, y=0.35, brightness=50),
        action(x=0.20, y=0.20, brightness=50),
    ])

    assert scene_color(dominant) != scene_color(even)


def test_colour_falls_back_to_temperature() -> None:
    """A white-only scene sets no xy at all, and white is still a colour."""
    warm = Scene(id="w", name="W", group_id=KITCHEN,
                 actions=[action(mirek=450, brightness=100)])
    cold = Scene(id="c", name="C", group_id=KITCHEN,
                 actions=[action(mirek=153, brightness=100)])

    assert scene_color(warm) is not None
    assert scene_color(cold) is not None
    assert scene_color(warm) != scene_color(cold)


def test_colour_of_nothing_is_none_rather_than_black() -> None:
    """Black is a colour a card would draw. Nothing is not."""
    assert scene_color(None) is None
    assert scene_color(Scene(id="s", name="S", group_id=KITCHEN)) is None
    assert scene_color(
        Scene(id="s", name="S", group_id=KITCHEN, actions=[action(brightness=80)])
    ) is None


# --------------------------------------------------- placing slots on the day

def _slots(*minutes: int | None) -> list[dict]:
    return [{"start_minutes": m} for m in minutes]


def test_a_schedule_that_wraps_past_midnight_moves_forward() -> None:
    """19:00, 22:00, 00:00. The bridge runs slots in LIST order, so the last
    one is tomorrow's midnight, five hours on -- not this morning's, nineteen
    hours back."""
    slots = _slots(19 * 60, 22 * 60, 0)
    _place_on_cycle(slots)

    assert [s["offset_minutes"] for s in slots] == [0, 180, 300]
    assert [s["start_resolved"] for s in slots] == ["19:00", "22:00", "00:00"]
    assert slots[-1]["duration_minutes"] == 24 * 60 - 300


def test_a_slot_overtaken_by_the_one_before_it_collapses() -> None:
    """The subtle one, and it was the other way round and wrong.

    A 19:00 slot sitting behind a 19:10 sunset is not skipped. The sunset
    scene starts, the bridge moves on to the next slot, finds its time
    already past, and fires it at once. So the SUNSET slot is the one that
    takes no time, and the 19:00 slot runs on to the next real transition.

    The bridge's own active_timeslot settled it: at 20:22, with the sunset
    scene at index 2 and the 19:00 one at index 3, it reported 3.
    """
    slots = _slots(17 * 60, 19 * 60 + 10, 19 * 60, 22 * 60)
    _place_on_cycle(slots)

    offsets = [s["offset_minutes"] for s in slots]
    durations = [s["duration_minutes"] for s in slots]

    # The overtaking pair land on the same moment...
    assert offsets[1] == offsets[2] == 130
    # ...and it is the one in FRONT that takes no time.
    assert durations[1] == 0
    assert durations[2] == 300 - 130


def test_a_day_nothing_can_be_resolved_for_is_left_unplaced() -> None:
    """Above the Arctic circle the sun may simply not rise. Inventing a
    timeline there would draw a schedule that does not exist."""
    slots = _slots(None, None)
    _place_on_cycle(slots)

    assert all(s["offset_minutes"] is None for s in slots)
    assert all(s["duration_minutes"] is None for s in slots)
    assert all(s["start_resolved"] is None for s in slots)


def test_an_unresolvable_slot_among_real_ones_anchors_to_a_real_one() -> None:
    """One unresolved sunset must not take the whole day down with it."""
    slots = _slots(None, 9 * 60, 14 * 60)
    _place_on_cycle(slots)

    assert slots[1]["start_resolved"] == "09:00"
    assert slots[2]["start_resolved"] == "14:00"


def test_no_slots_at_all_is_not_an_error() -> None:
    empty: list[dict] = []
    _place_on_cycle(empty)
    assert empty == []
