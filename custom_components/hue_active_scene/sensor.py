"""Active-scene sensors for Hue rooms and zones."""

from __future__ import annotations

import logging
from typing import Any

from aiohue.v2.scene_activity import SceneActivityTracker

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DATA_TRACKERS, DOMAIN, HUE_DOMAIN
from .smart_scene import timeslots_for_day, today_name

LOGGER = logging.getLogger(__name__)

STATE_NO_SCENE = "none"


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up active-scene sensors for every loaded Hue V2 bridge."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(HUE_DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not entries:
        # Hue has not finished setting up yet; Home Assistant will retry.
        raise PlatformNotReady("No loaded Philips Hue config entries found")

    hass.data.setdefault(DOMAIN, {DATA_TRACKERS: {}})
    trackers: dict[str, SceneActivityTracker] = hass.data[DOMAIN][DATA_TRACKERS]

    entities: list[HueActiveSceneSensor] = []

    for entry in entries:
        bridge = getattr(entry, "runtime_data", None)
        api = getattr(bridge, "api", None)
        if api is None:
            LOGGER.warning(
                "Hue entry %s exposes no usable API object; skipping", entry.entry_id
            )
            continue
        if getattr(bridge, "api_version", 2) == 1:
            LOGGER.debug("Skipping Hue V1 bridge %s", entry.entry_id)
            continue

        tracker = trackers.get(entry.entry_id)
        if tracker is None:
            tracker = SceneActivityTracker(api.scenes)
            tracker.start()
            trackers[entry.entry_id] = tracker
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _make_stopper(tracker))

        for group in [*api.groups.room, *api.groups.zone]:
            if not any(
                scene.group.rid == group.id for scene in api.scenes.scene
            ):
                # No scenes attached to this group; nothing to report.
                continue
            entities.append(
                HueActiveSceneSensor(api, tracker, group, entry.entry_id)
            )

        for smart_scene in api.scenes.smart_scene:
            entities.append(
                HueSmartSceneScheduleSensor(api, smart_scene, entry.entry_id)
            )

    async_add_entities(entities)


def _make_stopper(tracker: SceneActivityTracker):
    """Return a callback that stops the tracker on Home Assistant shutdown."""

    @callback
    def _stop(_event: Any) -> None:
        tracker.stop()

    return _stop


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
    ) -> None:
        """Initialise the sensor for a single Hue group."""
        self._api = api
        self._tracker = tracker
        self._group = group
        self._group_id = group.id
        self._attr_name = f"{group.metadata.name} active scene"
        self._attr_unique_id = f"{entry_id}_{group.id}_active_scene"
        # Attach to the virtual room/zone device the core Hue integration
        # already creates, so this sensor appears alongside its lights.
        self._attr_device_info = DeviceInfo(identifiers={(HUE_DOMAIN, group.id)})

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
        return {
            "group_name": self._group.metadata.name,
            "group_type": self._group.type.value,
            "scene_id": state.scene_id,
            # For a smart scene such as Golden hours, this is the underlying
            # regular scene currently in effect.
            "effective_scene": self._scene_name(state.effective_scene_id),
            "effective_scene_id": state.effective_scene_id,
            "is_smart_scene": bool(
                state.scene_id
                and state.effective_scene_id
                and state.scene_id != state.effective_scene_id
            ),
            "mode": mode.value if mode is not None else None,
            "last_recall": state.scene_last_recall,
            "speed": state.scene_speed,
            "brightness": brightness,
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

    def __init__(self, api: Any, smart_scene: Any, entry_id: str) -> None:
        """Initialise the sensor for a single smart scene."""
        self._api = api
        self._scene_id = smart_scene.id
        group_id = smart_scene.group.rid
        group = api.groups.get(group_id)
        group_name = getattr(getattr(group, "metadata", None), "name", "")
        scene_name = smart_scene.metadata.name
        self._attr_name = f"{group_name} {scene_name} schedule".strip()
        self._attr_unique_id = f"{entry_id}_{smart_scene.id}_schedule"
        if group is not None:
            self._attr_device_info = DeviceInfo(
                identifiers={(HUE_DOMAIN, group_id)}
            )

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
    def _handle_update(self, _event: Any, _resource: Any, **_kwargs: Any) -> None:
        """Write new state when the smart scene changes."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the scene currently in effect, or 'inactive'."""
        scene = self._scene
        if scene is None:
            return STATE_NO_SCENE
        if getattr(scene.state, "value", scene.state) != "active":
            return "inactive"

        slots = timeslots_for_day(self._api, scene, today_name())
        active = getattr(scene, "active_timeslot", None)
        index = getattr(active, "timeslot_id", None)
        for slot in slots:
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
            "timeslots": timeslots_for_day(self._api, scene, day),
        }
