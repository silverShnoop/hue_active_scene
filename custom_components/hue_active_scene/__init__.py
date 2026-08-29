"""Hue Active Scene.

A small companion integration that sits alongside the core Philips Hue
integration and reports which Hue scene is currently active in each room
or zone.

It does NOT replace or modify the core `hue` integration. It reuses the
bridge connection that `hue` already holds, so the core integration keeps
receiving its normal upgrades.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType

from .const import DATA_TRACKERS, DOMAIN

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Hue Active Scene integration from configuration.yaml."""
    if DOMAIN not in config:
        return True

    hass.data.setdefault(DOMAIN, {DATA_TRACKERS: {}})

    hass.async_create_task(
        async_load_platform(hass, Platform.SENSOR, DOMAIN, {}, config)
    )
    return True
