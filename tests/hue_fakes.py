"""Hue resources, shaped the way the bridge reports them.

aiohue's models are plain data holders, and every one of them is read
through `getattr` in the production code, so building them here supplies a
shape rather than faking a behaviour. Where a real object would carry an
enum, these carry one too -- `_enum_value` exists precisely because the
bridge's types are sometimes an enum and sometimes already a string, and a
fixture that only ever produced strings would never exercise it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


class Enumish:
    """Something with a `.value`, as aiohue's enums have."""

    def __init__(self, value: Any) -> None:
        self.value = value


def rtype(value: str) -> Enumish:
    """A resource-type marker, as a `services` entry carries."""
    return Enumish(value)


@dataclass
class Group:
    """A room or zone."""

    id: str
    name: str = "Room"
    type_: str = "room"
    services: list[Any] = field(default_factory=list)

    @property
    def metadata(self) -> Any:
        return SimpleNamespace(name=self.name)

    @property
    def type(self) -> Enumish:
        return Enumish(self.type_)


def service(kind: str, rid: str) -> Any:
    """One entry of a group's `services` list."""
    return SimpleNamespace(rtype=rtype(kind), rid=rid)


def action(x: float | None = None, y: float | None = None,
           brightness: float | None = None, mirek: int | None = None) -> Any:
    """One scene action: a light, and what the scene sets it to."""
    return SimpleNamespace(action=SimpleNamespace(
        dimming=None if brightness is None else SimpleNamespace(brightness=brightness),
        color=None if x is None else SimpleNamespace(xy=SimpleNamespace(x=x, y=y)),
        color_temperature=None if mirek is None else SimpleNamespace(mirek=mirek),
    ))


@dataclass
class Scene:
    """A regular scene attached to a group."""

    id: str
    name: str
    group_id: str
    actions: list[Any] = field(default_factory=list)

    @property
    def metadata(self) -> Any:
        return SimpleNamespace(name=self.name)

    @property
    def group(self) -> Any:
        return SimpleNamespace(rid=self.group_id)


def timeslot(scene_id: str, hours: int = 0, minutes: int = 0) -> Any:
    """One timeslot of a smart scene's weekly schedule."""
    return SimpleNamespace(
        target=SimpleNamespace(rid=scene_id),
        start_time=SimpleNamespace(
            kind=Enumish("time"),
            time=SimpleNamespace(hour=hours, minute=minutes, second=0),
        ),
    )


@dataclass
class SmartScene:
    """A smart scene: a group, and a schedule over the week."""

    id: str
    group_id: str
    week: list[Any] = field(default_factory=list)
    name: str = "Golden hours"

    @property
    def metadata(self) -> Any:
        return SimpleNamespace(name=self.name)

    @property
    def group(self) -> Any:
        return SimpleNamespace(rid=self.group_id)

    @property
    def week_timeslots(self) -> list[Any]:
        return self.week


def day_group(days: list[str], slots: list[Any]) -> Any:
    """One `week_timeslots` entry: which days, and the slots for them."""
    return SimpleNamespace(
        recurrence=[Enumish(d) for d in days],
        timeslots=slots,
    )


class Collection:
    """A controller's items, with aiohue's `get` and iteration."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def get(self, resource_id: str) -> Any | None:
        return next((i for i in self._items if i.id == resource_id), None)

    def __iter__(self):
        return iter(self._items)


class GroupedLights(Collection):
    """The grouped_light controller, which is the one that gets written to."""

    def __init__(self, items: list[Any]) -> None:
        super().__init__(items)
        self.calls: list[dict[str, Any]] = []

    async def set_state(self, resource_id: str, **kwargs: Any) -> None:
        """Record the call exactly as made.

        Kwargs rather than positional, deliberately: whether `on` is passed
        AT ALL is the single most important thing about this service, and a
        signature that accepted it positionally would hide that.
        """
        self.calls.append({"id": resource_id, **kwargs})


class Groups:
    """api.groups: rooms, zones and the grouped_lights behind them."""

    def __init__(self, rooms=(), zones=(), grouped=()) -> None:
        self.room = list(rooms)
        self.zone = list(zones)
        self.grouped_light = GroupedLights(list(grouped))

    def get(self, resource_id: str) -> Any | None:
        for item in [*self.room, *self.zone]:
            if item.id == resource_id:
                return item
        return None


class Scenes:
    """api.scenes: regular scenes and smart scenes."""

    def __init__(self, scenes=(), smart=()) -> None:
        self.scene = list(scenes)
        self.smart_scene = Collection(list(smart))

    def get(self, resource_id: str) -> Any | None:
        for item in [*self.scene, *self.smart_scene]:
            if item.id == resource_id:
                return item
        return None


class Api:
    """One bridge."""

    def __init__(self, groups: Groups, scenes: Scenes | None = None) -> None:
        self.groups = groups
        self.scenes = scenes or Scenes()


def bridge(api: Api, entry_id: str = "hue_entry") -> Any:
    """A TrackedBridge, as the integration's runtime_data holds them."""
    return SimpleNamespace(api=api, entry_id=entry_id, tracker=None)
