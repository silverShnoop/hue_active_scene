"""Config flow for the Hue Active Scene companion integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

TITLE = "Hue Active Scene"


class HueActiveSceneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the (option-less) config flow.

    There is nothing to configure: the integration discovers every Hue V2
    bridge Home Assistant has already set up. The entry exists only so the
    sensors can be attached to the Hue room/zone devices.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow started from the UI."""
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title=TITLE, data={})

    async def async_step_import(
        self, import_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle the flow started by `hue_active_scene:` in configuration.yaml."""
        return self.async_create_entry(title=TITLE, data={})
