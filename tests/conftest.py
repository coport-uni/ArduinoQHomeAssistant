"""Shared fixtures for myhyundai_aircon tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load integrations from this repo."""
    return
