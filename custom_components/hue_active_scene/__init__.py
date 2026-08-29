"""Hue Active Scene.

A small companion integration that sits alongside the core Philips Hue
integration and reports which Hue scene is currently active in each room
or zone.

It does NOT replace or modify the core `hue` integration. It reuses the
bridge connection that `hue` already holds, so the core integration keeps
receiving its normal upgrades.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from aiohue.v2.scene_activity import SceneActivityTracker

from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, HUE_DOMAIN

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = [Platform.SENSOR]


@dataclass(slots=True)
class TrackedBridge:
    """A Hue V2 bridge we borrow, and the scene tracker watching it."""

    entry_id: str
    api: Any
    tracker: SceneActivityTracker


type HueActiveSceneConfigEntry = ConfigEntry[list[TrackedBridge]]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from configuration.yaml.

    The sensors are attached to the room/zone devices that core Hue creates,
    and Home Assistant only allows that for entities belonging to a config
    entry. So the YAML key just starts an import flow; the entry it creates
    does the real work.
    """
    if DOMAIN not in config:
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data={}
        )
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: HueActiveSceneConfigEntry
) -> bool:
    """Set up scene tracking for every loaded Hue V2 bridge."""
    bridges: list[TrackedBridge] = []

    for hue_entry in hass.config_entries.async_entries(HUE_DOMAIN):
        # Reload ourselves when a bridge we borrow is reloaded or removed:
        # its `runtime_data` (and the API object underneath) is replaced, so
        # our tracker and sensors would otherwise hold a dead connection.
        entry.async_on_unload(
            hue_entry.async_on_state_change(_make_reloader(hass, entry))
        )

        if hue_entry.state is not ConfigEntryState.LOADED:
            continue

        bridge = getattr(hue_entry, "runtime_data", None)
        api = getattr(bridge, "api", None)
        if api is None or getattr(bridge, "api_version", 2) == 1:
            # V1 bridges have no scene activity to report.
            continue

        tracker = SceneActivityTracker(api.scenes)
        tracker.start()
        entry.async_on_unload(tracker.stop)
        bridges.append(TrackedBridge(hue_entry.entry_id, api, tracker))

    if not bridges:
        raise ConfigEntryNotReady("No loaded Philips Hue V2 config entries found")

    entry.runtime_data = bridges
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: HueActiveSceneConfigEntry
) -> bool:
    """Unload the config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _make_reloader(
    hass: HomeAssistant, entry: HueActiveSceneConfigEntry
) -> Any:
    """Return a callback that reloads our entry when a Hue entry changes."""

    @callback
    def _reload() -> None:
        # Entries also change state while Home Assistant shuts down; a reload
        # then is pointless noise.
        if hass.is_stopping:
            return
        hass.config_entries.async_schedule_reload(entry.entry_id)

    return _reload
