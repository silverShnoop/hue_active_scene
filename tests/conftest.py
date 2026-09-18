"""Test setup for the Hue Active Scene companion integration.

The tests run against a real Home Assistant, installed by
`pytest-homeassistant-custom-component`, rather than against stand-ins for
it. That matters more here than it usually would: almost everything this
integration does is read Hue's own data shapes and hand them to Home
Assistant's helpers, so a stand-in for either end would mostly be testing
itself. The Hue resources ARE built here, because aiohue's models are plain
data holders and the production code reads every one of them through
`getattr` -- supplying the shape is not the same as faking behaviour.
"""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant see custom_components/ in every test."""
    return enable_custom_integrations
