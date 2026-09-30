"""Remember the scene a room was on, and what ended it.

The bridge forgets a scene the moment it stops being true. Change one bulb in
a room -- by hand, or by recalling a scene on a zone that shares the bulb --
and the room's scene goes `inactive`, and the tracker reports no scene at all.
Recorder history in this house shows it every time: the Far light zone goes
to Bright and the Bedroom drops from Nightlight to nothing thirty milliseconds
later, and it does not come back when the lamp goes off again.

That leaves a card able to say only "no scene", when the two useful facts are
which scene the room was on (so one press restores it) and which group took
it (so the reason is on the screen). This module keeps both.

"Which group" is a matter of timing and membership, because the bridge never
says. A group that starts a scene within `WINDOW` of this one losing its
scene, and that shares at least one bulb with it, is the one that ended it.
The two events can arrive in either order -- the zone's `static` usually
lands first, but nothing promises that -- so an ending waits for a starter as
well as looking back for one.

What it cannot see: a group with no scenes. A zone like the whole-house Home
zone has no scene to start, so dimming it ends every room's scene and names
nobody. The ending is still recorded; `ended_by` is simply left empty rather
than guessed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

# Long enough for two bridge events about one command to land, short enough
# that a lamp switched on a minute after the room was dimmed is not blamed.
WINDOW = timedelta(seconds=2)

Listener = Callable[[str], None]


@dataclass(slots=True)
class Ending:
    """The scene a group was on until it stopped, and why."""

    scene_id: str
    at: datetime
    ended_by: str | None = None


def group_lights(api: Any, group_id: str) -> frozenset[str]:
    """Return the ids of the lights in a room or zone.

    Rooms hold devices and zones hold lights, which is why aiohue gives each
    controller its own `get_lights`. Read afresh every time: a zone can be
    edited in the Hue app while this is running.
    """
    for controller in (api.groups.room, api.groups.zone):
        get_lights = getattr(controller, "get_lights", None)
        if get_lights is None:
            continue
        lights = get_lights(group_id)
        if lights:
            return frozenset(light.id for light in lights)
    return frozenset()


class SceneEndings:
    """Follow every group on one bridge and keep its last scene."""

    def __init__(
        self,
        api: Any,
        tracker: Any,
        now: Callable[[], datetime] = dt_util.utcnow,
    ) -> None:
        """Initialise against a started scene tracker."""
        self._api = api
        self._tracker = tracker
        self._now = now
        # What each group was showing when we last looked. The tracker only
        # says what is true now; an ending is the difference between the two.
        self._current: dict[str, str | None] = {}
        self._started: dict[str, datetime] = {}
        self._endings: dict[str, Ending] = {}
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        self._unsubs: list[Callable[[], None]] = []

    def start(self, group_ids: list[str]) -> None:
        """Watch these groups. Their present scenes are the starting point."""
        for group_id in group_ids:
            self._current[group_id] = self._tracker.get_group_state(
                group_id
            ).scene_id
            self._unsubs.append(
                self._tracker.subscribe(group_id, self._handle_update)
            )

    def stop(self) -> None:
        """Stop watching."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def ending(self, group_id: str) -> Ending | None:
        """Return how this group's last scene ended, if it is not on one."""
        return self._endings.get(group_id)

    def subscribe(self, group_id: str, listener: Listener) -> Callable[[], None]:
        """Call `listener` whenever this group's scene or its ending changes."""
        self._listeners[group_id].append(listener)

        def _remove() -> None:
            self._listeners[group_id].remove(listener)

        return _remove

    def _notify(self, group_id: str) -> None:
        for listener in list(self._listeners.get(group_id, [])):
            listener(group_id)

    def _shares_lights(self, one: str, other: str) -> bool:
        return bool(
            group_lights(self._api, one) & group_lights(self._api, other)
        )

    def _handle_update(self, group_id: str) -> None:
        now = self._now()
        before = self._current.get(group_id)
        after = self._tracker.get_group_state(group_id).scene_id
        self._current[group_id] = after
        blamed: list[str] = []

        if after is not None and after != before:
            # A scene started here: whatever this group was waiting to be
            # restored to is no longer the point.
            self._started[group_id] = now
            self._endings.pop(group_id, None)
            # And if a neighbour lost its scene a moment ago with nobody to
            # blame, this is who.
            for other, ending in self._endings.items():
                if (
                    other != group_id
                    and ending.ended_by is None
                    and now - ending.at <= WINDOW
                    and self._shares_lights(other, group_id)
                ):
                    ending.ended_by = group_id
                    blamed.append(other)
        elif after is None and before is not None:
            self._endings[group_id] = Ending(
                scene_id=before, at=now, ended_by=self._starter(group_id, now)
            )

        self._notify(group_id)
        for other in blamed:
            self._notify(other)

    def _starter(self, group_id: str, now: datetime) -> str | None:
        """The neighbour that started a scene just before this one ended."""
        candidates = [
            (started, other)
            for other, started in self._started.items()
            if other != group_id
            and now - started <= WINDOW
            and self._current.get(other) is not None
            and self._shares_lights(group_id, other)
        ]
        if not candidates:
            return None
        return max(candidates)[1]
