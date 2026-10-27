"""Config flow tests."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.air_by_nature.const import CONF_GROUP_ID, CONF_TOKENS, DOMAIN

from .conftest import GROUPS_URL, TOKEN_RESPONSE, TOKEN_URL

CREDS = {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture(autouse=True)
def no_setup():
    """Do not set the entry up after the flow."""
    with patch("custom_components.air_by_nature.async_setup_entry", return_value=True):
        yield


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_single_group(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """One home: entry is created straight away, password is not stored."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(GROUPS_URL, json={"data": [{"id": 100, "name": "Home"}]})

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "100"
    assert result["title"] == "Home"
    data = result["data"]
    assert data[CONF_GROUP_ID] == 100
    assert data[CONF_USERNAME] == "user@example.com"
    assert CONF_PASSWORD not in data
    assert data[CONF_TOKENS]["access_token"] == "new-access"

    # Password grant sent with the web app's public client.
    _, _, form, _ = aioclient_mock.mock_calls[0]
    assert form["grant_type"] == "password"
    assert form["client_id"] == "1"
    assert form["client_secret"] == "angular-app"


async def test_multiple_groups(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Several homes: user picks one."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(
        GROUPS_URL, json={"data": [{"id": 100, "name": "Home"}, {"id": 700, "name": "Cabin"}]}
    )
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "group"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GROUP_ID: "700"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_GROUP_ID] == 700
    # Titled after the chosen home, so two homes can be told apart.
    assert result["title"] == "Cabin"


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 400, "json": {"error": "invalid_grant"}}, "invalid_auth"),
        ({"status": 500}, "cannot_connect"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
    ],
)
async def test_login_errors_then_recover(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_kwargs, error
) -> None:
    """Errors show on the form, and the flow can still finish."""
    aioclient_mock.post(TOKEN_URL, **mock_kwargs)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(GROUPS_URL, json={"data": [{"id": 100, "name": "Home"}]})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_no_groups(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Account without homes aborts."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(GROUPS_URL, json={"data": []})
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_groups"


async def test_already_configured(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Same home twice aborts."""
    config_entry.add_to_hass(hass)
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(GROUPS_URL, json={"data": [{"id": 100, "name": "Home"}]})
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Reauth asks only for the password and stores fresh tokens."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "right"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKENS]["access_token"] == "new-access"
    _, _, form, _ = aioclient_mock.mock_calls[0]
    assert form["username"] == "user@example.com"


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 401}, "invalid_auth"),
        ({"status": 403}, "cannot_connect"),
        ({"status": 500}, "cannot_connect"),
        ({"json": {"data": [{"name": "no id"}]}}, "cannot_connect"),
    ],
)
async def test_group_list_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_kwargs, error
) -> None:
    """Login works but listing homes fails: error on the form, no crash."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(GROUPS_URL, **mock_kwargs)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_unexpected_error(hass: HomeAssistant) -> None:
    """A bug in the client shows a generic error instead of a stack trace."""
    result = await _start(hass)
    with patch(
        "custom_components.air_by_nature.config_flow.AirByNatureClient.login",
        side_effect=RuntimeError,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["errors"] == {"base": "unknown"}


async def test_password_not_echoed_after_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """After a failed login the email is kept but the password is not sent back."""
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    }
    assert suggested.get(CONF_USERNAME) == "user@example.com"
    assert suggested.get(CONF_PASSWORD) is None
