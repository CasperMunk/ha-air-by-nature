"""Shared fixtures."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.air_by_nature.const import CONF_GROUP_ID, CONF_TOKENS, DOMAIN

BASE = "https://admin.airbynature.com"
TOKEN_URL = f"{BASE}/oauth/token"
GROUPS_URL = f"{BASE}/api/user-app/devicegroups"
GROUP_URL = f"{GROUPS_URL}/100"
DOWNSTAIRS_URL = f"{GROUP_URL}/devices/1002"
UPSTAIRS_URL = f"{GROUP_URL}/devices/1001"

GROUP_JSON: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "group.json").read_text()
)

TOKEN_RESPONSE = {
    "token_type": "Bearer",
    "expires_in": 31536000,
    "access_token": "new-access",
    "refresh_token": "new-refresh",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
def group_json() -> dict[str, Any]:
    """A fresh copy of the live-shaped group response."""
    return copy.deepcopy(GROUP_JSON)


def make_tokens(expires_in: timedelta = timedelta(days=300)) -> dict[str, str]:
    """Stored token dict."""
    return {
        "access_token": "stored-access",
        "refresh_token": "stored-refresh",
        "expires_at": (dt_util.utcnow() + expires_in).isoformat(),
    }


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Entry for group 100."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Air by Nature",
        unique_id="100",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_GROUP_ID: 100,
            CONF_TOKENS: make_tokens(),
        },
    )


@pytest.fixture
def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    group_json: dict[str, Any],
) -> Callable[[], Any]:
    """Return a coroutine factory that sets up the entry against the mock API."""

    async def _setup() -> MockConfigEntry:
        aioclient_mock.get(GROUP_URL, json=group_json)
        if hass.config_entries.async_get_entry(config_entry.entry_id) is None:
            config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        return config_entry

    return _setup
