"""API client: token handling and malformed responses."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.air_by_nature.api import (
    AirByNatureAuthError,
    AirByNatureClient,
    AirByNatureConnectionError,
    Tokens,
)

from .conftest import GROUP_URL, GROUPS_URL, TOKEN_RESPONSE, TOKEN_URL, make_tokens


def _client(hass: HomeAssistant, expires_in: timedelta = timedelta(days=300)) -> AirByNatureClient:
    return AirByNatureClient(
        async_get_clientsession(hass), Tokens.from_dict(make_tokens(expires_in))
    )


def _token_posts(aioclient_mock: AiohttpClientMocker) -> int:
    return sum(1 for method, url, _, _ in aioclient_mock.mock_calls if str(url) == TOKEN_URL)


async def test_concurrent_requests_refresh_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, group_json: dict[str, Any]
) -> None:
    """A poll and a command racing on an expiring token share one refresh."""

    async def slow_token(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        await asyncio.sleep(0.01)  # let the other request reach the token check
        return AiohttpClientMockResponse(method, url, json=TOKEN_RESPONSE)

    aioclient_mock.post(TOKEN_URL, side_effect=slow_token)
    aioclient_mock.get(GROUP_URL, json=group_json)
    client = _client(hass, timedelta(days=1))

    await asyncio.gather(client.get_group(100), client.get_group(100))

    assert _token_posts(aioclient_mock) == 1
    assert client.tokens is not None
    assert client.tokens.access_token == "new-access"


async def test_401_refreshes_once_and_retries(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, group_json: dict[str, Any]
) -> None:
    """A token revoked early is refreshed, and the request is retried with the new one."""

    async def revoked_then_ok(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        if _token_posts(aioclient_mock) == 0:
            return AiohttpClientMockResponse(method, url, status=401)
        return AiohttpClientMockResponse(method, url, json=group_json)

    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(GROUP_URL, side_effect=revoked_then_ok)
    saved: list[Tokens] = []
    client = _client(hass)
    client.add_token_listener(saved.append)

    group = await client.get_group(100)

    assert group.id == 100
    assert _token_posts(aioclient_mock) == 1
    assert [t.access_token for t in saved] == ["new-access"]
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer new-access"


async def test_second_401_is_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A fresh token that is still rejected means the account lost access."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    aioclient_mock.get(GROUP_URL, status=401)
    with pytest.raises(AirByNatureAuthError):
        await _client(hass).get_group(100)
    assert _token_posts(aioclient_mock) == 1


@pytest.mark.parametrize(
    ("url", "mock_kwargs"),
    [
        (GROUP_URL, {"text": "<html>maintenance</html>", "headers": {"Content-Type": "text/html"}}),
        (GROUP_URL, {"text": "{not json", "headers": {"Content-Type": "application/json"}}),
        (GROUP_URL, {"json": {"message": "no data key"}}),
        (GROUP_URL, {"json": {"data": {"devices": []}}}),
        (GROUP_URL, {"status": 403}),
        (GROUPS_URL, {"json": {"data": [{"name": "no id"}]}}),
        (GROUPS_URL, {"json": {"data": {"id": 100}}}),
    ],
)
async def test_bad_responses_raise_api_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, url: str, mock_kwargs: dict[str, Any]
) -> None:
    """Odd server replies become API errors, never raw exceptions."""
    aioclient_mock.get(url, **mock_kwargs)
    client = _client(hass)
    call = client.list_groups() if url == GROUPS_URL else client.get_group(100)
    with pytest.raises((AirByNatureConnectionError, AirByNatureAuthError)):
        await call


async def test_malformed_token_response(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A token reply without tokens is a connection error, not a crash."""
    aioclient_mock.post(TOKEN_URL, json={"token_type": "Bearer"})
    client = AirByNatureClient(async_get_clientsession(hass))
    with pytest.raises(AirByNatureConnectionError):
        await client.login("user@example.com", "secret")


async def test_level_out_of_range(hass: HomeAssistant) -> None:
    """Levels outside 0-5 never reach the cloud."""
    with pytest.raises(ValueError, match="Level must be"):
        await _client(hass).set_comfort_level(100, 1002, 6)


async def test_no_tokens(hass: HomeAssistant) -> None:
    """Requests and refresh without tokens are auth errors."""
    client = AirByNatureClient(async_get_clientsession(hass))
    with pytest.raises(AirByNatureAuthError):
        await client.get_group(100)
    with pytest.raises(AirByNatureAuthError):
        await client.refresh()


async def test_redirects_are_not_followed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A redirect on login is an error; the password is never re-posted elsewhere."""
    aioclient_mock.post(TOKEN_URL, status=307, headers={"Location": "https://evil.example/"})
    client = AirByNatureClient(async_get_clientsession(hass))
    with pytest.raises(AirByNatureConnectionError):
        await client.login("user@example.com", "secret")
    assert all("evil" not in str(url) for _, url, _, _ in aioclient_mock.mock_calls)


async def test_redirect_on_api_request_is_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A redirect on an API call is an error, not a parse of the redirect body."""
    aioclient_mock.get(GROUP_URL, status=302, headers={"Location": "https://evil.example/"})
    with pytest.raises(AirByNatureConnectionError):
        await _client(hass).get_group(100)


@pytest.mark.parametrize(
    ("expires_in", "refresh_after"),
    [
        (31536000, timedelta(days=365 - 7)),  # 1 year: a week early
        (3600, timedelta(minutes=30)),  # 1 hour: halfway, not on every request
    ],
)
def test_refresh_time_scales_with_lifetime(expires_in: int, refresh_after: timedelta) -> None:
    """Short-lived tokens are not refreshed on every request."""
    tokens = Tokens.from_response({**TOKEN_RESPONSE, "expires_in": expires_in})
    assert tokens.refresh_at - (tokens.expires_at - timedelta(seconds=expires_in)) == refresh_after
    assert not tokens.needs_refresh()
    assert Tokens.from_dict(tokens.as_dict()) == tokens


@pytest.mark.parametrize("expires_in", [0, -5, 10**20, "soon"])
def test_bad_token_lifetime(expires_in: Any) -> None:
    """Zero, negative, absurd or non-numeric lifetimes are rejected."""
    with pytest.raises(AirByNatureConnectionError):
        Tokens.from_response({**TOKEN_RESPONSE, "expires_in": expires_in})


@pytest.mark.parametrize(
    "body",
    [
        {"data": [1, 2]},
        {"data": {"id": 100, "devices": ["not a device"]}},
        {"data": {"id": 100, "devices": [{"name": "no id"}]}},
    ],
)
async def test_malformed_group(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: dict[str, Any]
) -> None:
    """Wrong shapes inside the group reply are connection errors."""
    aioclient_mock.get(GROUP_URL, json=body)
    with pytest.raises(AirByNatureConnectionError):
        await _client(hass).get_group(100)


async def test_out_of_range_level_is_clamped(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, group_json: dict[str, Any]
) -> None:
    """A level outside 0-5 from the cloud never gives a fan above 100 % or below 0 %."""
    group_json["data"]["devices"][0]["comfort_level"] = 7
    group_json["data"]["devices"][1]["comfort_level"] = -1
    aioclient_mock.get(GROUP_URL, json=group_json)
    group = await _client(hass).get_group(100)
    assert [d.comfort_level for d in group.devices.values()] == [5, 0]


@pytest.mark.parametrize("stored", [None, "high", 9, [3]])
async def test_odd_stored_level_falls_back(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, stored: Any
) -> None:
    """An unusable level in the PATCH reply falls back to the level we sent."""
    aioclient_mock.patch(f"{GROUP_URL}/devices/1002", json={"data": {"comfort_level": stored}})
    assert await _client(hass).set_comfort_level(100, 1002, 2) == 2
