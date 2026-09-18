"""Active-scene sensors for Hue rooms and zones."""

from __future__ import annotations

from typing import Any

from aiohue.v2.scene_activity import SceneActivityTracker

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HueActiveSceneConfigEntry
from .const import HUE_DOMAIN
from .smart_scene import room_scenes, timeslots_for_day, today_name

STATE_NO_SCENE = "none"
STATE_INACTIVE = "inactive"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HueActiveSceneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up active-scene sensors for every borrowed Hue V2 bridge."""
    dev_reg = dr.async_get(hass)
    entities: list[SensorEntity] = []

    def hue_device(group_id: str, hue_entry_id: str) -> DeviceEntry | None:
        """Return core Hue's device for a group, which setup has us sharing.

        Looked up against the Hue entry so it cannot resolve to anything but
        the real room or zone. None means no device rather than a new one:
        a nameless device of our own is worse than none at all.
        """
        return dev_reg.async_get_device_by_identifier(
            (HUE_DOMAIN, group_id), hue_entry_id
        )

    for bridge in entry.runtime_data:
        api = bridge.api

        for group in [*api.groups.room, *api.groups.zone]:
            if not any(scene.group.rid == group.id for scene in api.scenes.scene):
                # No scenes attached to this group; nothing to report.
                continue
            entities.append(
                HueActiveSceneSensor(
                    api,
                    bridge.tracker,
                    group,
                    bridge.entry_id,
                    hue_device(group.id, bridge.entry_id),
                )
            )

        for smart_scene in api.scenes.smart_scene:
            entities.append(
                HueSmartSceneScheduleSensor(
                    api,
                    smart_scene,
                    bridge.entry_id,
                    hue_device(smart_scene.group.rid, bridge.entry_id),
                )
            )

    async_add_entities(entities)


class HueActiveSceneSensor(SensorEntity):
    """Report the Hue scene currently active in one room or zone."""

    _attr_should_poll = False
    _attr_icon = "mdi:palette"

    def __init__(
        self,
        api: Any,
        tracker: SceneActivityTracker,
        group: Any,
        entry_id: str,
        device: DeviceEntry | None,
    ) -> None:
        """Initialise the sensor for a single Hue group."""
        self._api = api
        self._tracker = tracker
        self._group = group
        self._group_id = group.id
        # The name is given in full rather than via `has_entity_name`, which
        # would compose it from the device and repeat the room: "Kitchen
        # Kitchen active scene".
        self._attr_name = f"{group.metadata.name} active scene"
        self._attr_unique_id = f"{entry_id}_{group.id}_active_scene"
        # Sit on core Hue's own room/zone device, which setup shared with this
        # entry. Assigning `device_entry` attaches to that exact device;
        # `DeviceInfo` would instead look the identifier up against this entry
        # and make a nameless duplicate.
        self.device_entry = device

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracker updates for this group."""
        self.async_on_remove(
            self._tracker.subscribe(self._group_id, self._handle_update)
        )

    @callback
    def _handle_update(self, _group_id: str) -> None:
        """Write new state when the active scene for this group changes."""
        self.async_write_ha_state()

    def _scene_name(self, scene_id: str | None) -> str | None:
        """Resolve a Hue scene id to its display name."""
        if not scene_id:
            return None
        if (scene := self._api.scenes.get(scene_id)) is None:
            return None
        return scene.metadata.name

    @property
    def native_value(self) -> str:
        """Return the name of the active scene, or 'none'."""
        state = self._tracker.get_group_state(self._group_id)
        return self._scene_name(state.scene_id) or STATE_NO_SCENE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detail about the active scene."""
        state = self._tracker.get_group_state(self._group_id)
        mode = state.scene_mode
        brightness = state.scene_brightness
        if brightness is not None:
            # Hue reports brightness as 0-100; match Home Assistant's 0-255.
            brightness = round((brightness / 100) * 255)
        last_recall = state.scene_last_recall
        return {
            "group_name": self._group.metadata.name,
            "group_type": self._group.type.value,
            "scene_id": state.scene_id,
            # While a smart scene is running, this is the underlying regular
            # scene currently in effect.
            "effective_scene": self._scene_name(state.effective_scene_id),
            "effective_scene_id": state.effective_scene_id,
            "is_smart_scene": bool(
                state.scene_id
                and state.effective_scene_id
                and state.scene_id != state.effective_scene_id
            ),
            "mode": mode.value if mode is not None else None,
            "last_recall": last_recall.isoformat() if last_recall else None,
            "speed": state.scene_speed,
            "brightness": brightness,
            # Every scene this room can be set to, each with the colour its
            # own actions average to and whether the schedule already drives
            # it. Core Hue gives a dashboard the scene entities and nothing
            # else, so a card offering the scenes a schedule does not cover
            # has no way to know which those are, nor what any of them look
            # like.
            "scenes": room_scenes(self._api, self._group_id),
        }


class HueSmartSceneScheduleSensor(SensorEntity):
    """Expose a Hue smart scene's schedule for today.

    State is the scene currently in effect, or `inactive` when the smart
    scene isn't running. Attributes carry today's full timeslot list —
    start time, target scene name and a derived hex colour per slot — which
    the core Hue integration does not expose.
    """

    _attr_should_poll = False
    _attr_icon = "mdi:sun-clock"

    def __init__(
        self,
        api: Any,
        smart_scene: Any,
        entry_id: str,
        device: DeviceEntry | None,
    ) -> None:
        """Initialise the sensor for a single smart scene."""
        self._api = api
        self._scene_id = smart_scene.id
        group_id = smart_scene.group.rid
        group = api.groups.get(group_id)
        group_name = getattr(getattr(group, "metadata", None), "name", "")
        scene_name = smart_scene.metadata.name
        self._attr_name = f"{group_name} {scene_name} schedule".strip()
        self._attr_unique_id = f"{entry_id}_{smart_scene.id}_schedule"
        self.device_entry = device

    @property
    def _scene(self) -> Any:
        """Return the live smart scene resource."""
        return self._api.scenes.smart_scene.get(self._scene_id)

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates for this smart scene."""
        self.async_on_remove(
            self._api.scenes.smart_scene.subscribe(
                self._handle_update, id_filter=self._scene_id
            )
        )

    @callback
    def _handle_update(self, _event_type: Any, _resource: Any) -> None:
        """Write new state when the smart scene changes."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return whether the smart scene still exists on the bridge."""
        return self._scene is not None

    @property
    def native_value(self) -> str:
        """Return the scene currently in effect, or 'inactive'."""
        scene = self._scene
        if scene is None:
            return STATE_NO_SCENE
        if getattr(scene.state, "value", scene.state) != "active":
            return STATE_INACTIVE

        active = getattr(scene, "active_timeslot", None)
        index = getattr(active, "timeslot_id", None)
        weekday = getattr(active, "weekday", None)
        day = getattr(weekday, "value", weekday) or today_name()
        for slot in timeslots_for_day(self.hass, self._api, scene, day):
            if slot["index"] == index:
                return slot["scene"] or STATE_NO_SCENE
        return STATE_NO_SCENE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return today's timeslots and which one is active."""
        scene = self._scene
        if scene is None:
            return {}

        active = getattr(scene, "active_timeslot", None)
        weekday = getattr(active, "weekday", None)
        day = getattr(weekday, "value", weekday) or today_name()

        return {
            "scene_name": scene.metadata.name,
            "is_active": getattr(scene.state, "value", scene.state) == "active",
            "active_index": getattr(active, "timeslot_id", None),
            "weekday": day,
            "transition_duration": getattr(scene, "transition_duration", None),
            "timeslots": timeslots_for_day(self.hass, self._api, scene, day),
        }
