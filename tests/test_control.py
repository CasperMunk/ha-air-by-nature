"""Fan and select control."""

from __future__ import annotations

import pytest
from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    SERVICE_SET_PERCENTAGE,
)
from homeassistant.components.fan import (
    DOMAIN as FAN_DOMAIN,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import DOWNSTAIRS_URL, TOKEN_URL

FAN = "fan.downstairs"
SELECT = "select.downstairs_comfort_level"


def _patches(aioclient_mock: AiohttpClientMocker) -> list[dict]:
    return [
        data for method, _url, data, _ in aioclient_mock.mock_calls if method.lower() == "patch"
    ]


def _mock_patch(aioclient_mock: AiohttpClientMocker, level: int) -> None:
    aioclient_mock.patch(DOWNSTAIRS_URL, json={"data": {"id": 1002, "comfort_level": level}})


@pytest.mark.parametrize(
    ("percentage", "level"), [(100, 5), (80, 4), (60, 3), (50, 3), (21, 2), (1, 1), (0, 0)]
)
async def test_set_percentage(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker, percentage, level
) -> None:
    """Percentages map to levels 0-5 and are reflected at once."""
    await setup_integration()
    _mock_patch(aioclient_mock, level)
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PERCENTAGE,
        {ATTR_ENTITY_ID: FAN, ATTR_PERCENTAGE: percentage},
        blocking=True,
    )
    assert _patches(aioclient_mock) == [{"comfort_level": level}]
    assert hass.states.get(FAN).attributes["comfort_level"] == level


async def test_off_then_on_restores_level(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """turn_on without a speed goes back to the level before turn_off."""
    await setup_integration()
    _mock_patch(aioclient_mock, 0)
    await hass.services.async_call(
        FAN_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: FAN}, blocking=True
    )
    assert hass.states.get(FAN).state == STATE_OFF
    assert hass.states.get(SELECT).state == "off"

    aioclient_mock.clear_requests()
    _mock_patch(aioclient_mock, 4)
    await hass.services.async_call(
        FAN_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: FAN}, blocking=True
    )
    assert _patches(aioclient_mock) == [{"comfort_level": 4}]


async def test_select_option(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """Select writes the matching level."""
    await setup_integration()
    _mock_patch(aioclient_mock, 1)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: SELECT, ATTR_OPTION: "very_quiet"},
        blocking=True,
    )
    assert _patches(aioclient_mock) == [{"comfort_level": 1}]
    assert hass.states.get(FAN).attributes["percentage"] == 20


async def test_write_failure_raises(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failed write surfaces as an error and leaves state unchanged."""
    await setup_integration()
    aioclient_mock.patch(DOWNSTAIRS_URL, status=500)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            FAN_DOMAIN,
            SERVICE_SET_PERCENTAGE,
            {ATTR_ENTITY_ID: FAN, ATTR_PERCENTAGE: 20},
            blocking=True,
        )
    assert hass.states.get(FAN).attributes["comfort_level"] == 4


async def test_turn_on_with_percentage(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """turn_on with a speed sets that speed."""
    await setup_integration()
    _mock_patch(aioclient_mock, 2)
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: FAN, ATTR_PERCENTAGE: 40},
        blocking=True,
    )
    assert _patches(aioclient_mock) == [{"comfort_level": 2}]


async def test_write_auth_failure_starts_reauth(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """Rejected login on a write raises and asks the user to log in again."""
    entry = await setup_integration()
    aioclient_mock.patch(DOWNSTAIRS_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            FAN_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: FAN}, blocking=True
        )
    flows = hass.config_entries.flow.async_progress()
    assert any(
        f["context"]["source"] == SOURCE_REAUTH and f["context"]["entry_id"] == entry.entry_id
        for f in flows
    )
