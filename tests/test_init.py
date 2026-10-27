"""Setup, entities, token handling and diagnostics."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.air_by_nature.const import CONF_TOKENS, DOMAIN
from custom_components.air_by_nature.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import GROUP_URL, TOKEN_RESPONSE, TOKEN_URL, make_tokens

UP = "upstairs"
DOWN = "downstairs"


async def test_setup_creates_entities(hass: HomeAssistant, setup_integration) -> None:
    """Both units appear with the right values."""
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.LOADED

    up = hass.states.get(f"fan.{UP}")
    assert up.state == STATE_ON
    assert up.attributes["percentage"] == 100
    assert up.attributes["comfort_level"] == 5
    assert hass.states.get(f"fan.{DOWN}").attributes["percentage"] == 80

    assert hass.states.get(f"select.{DOWN}_comfort_level").state == "high"
    assert hass.states.get(f"sensor.{DOWN}_carbon_dioxide").state == "434.99"
    assert hass.states.get(f"sensor.{DOWN}_supply_air_temperature").state == "19.18"
    assert hass.states.get(f"sensor.{UP}_outdoor_temperature").state == "16.46"
    assert hass.states.get(f"binary_sensor.{UP}_online").state == STATE_ON
    assert hass.states.get("sensor.test_home_active_rule").state == "Luftskifte 1"

    # RPM sensors exist but are disabled by default.
    ent = er.async_get(hass).async_get(f"sensor.{DOWN}_supply_fan_speed")
    assert ent is not None
    assert ent.disabled_by is not None

    # Units hang under the home device.
    devreg = dr.async_get(hass)
    home = devreg.async_get_device_by_identifier((DOMAIN, "group_100"), entry.entry_id)
    unit = devreg.async_get_device_by_identifier((DOMAIN, "1002"), entry.entry_id)
    assert unit.via_device_id == home.id
    assert unit.model == "Main unit v2"
    # The home is named after the cloud's home, not the integration.
    assert home.name == "Test Home"
    assert home.model == "Home"


async def test_home_device_renamed_on_upgrade(
    hass: HomeAssistant, setup_integration, config_entry
) -> None:
    """A home device from 0.1.0 (named "Air by Nature") takes the home's name.

    Entity ids stay as they were, and a name the user set is kept.
    """
    config_entry.add_to_hass(hass)
    devreg = dr.async_get(hass)
    old = devreg.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "group_100")},
        name="Air by Nature",
        model="Device group",
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        "group_100_active_rule",
        config_entry=config_entry,
        device_id=old.id,
        suggested_object_id="air_by_nature_active_rule",
    )
    devreg.async_update_device(old.id, name_by_user="Ventilation schedule")

    await setup_integration()
    home = devreg.async_get(old.id)
    assert (home.name, home.model, home.name_by_user) == (
        "Test Home",
        "Home",
        "Ventilation schedule",
    )
    assert hass.states.get("sensor.air_by_nature_active_rule").state == "Luftskifte 1"


async def test_offline_unit(hass: HomeAssistant, setup_integration, group_json) -> None:
    """Offline unit: readings unavailable, online sensor says off."""
    group_json["data"]["devices"][0].update(is_online=False, wifi_signal=0, latest_history=None)
    await setup_integration()
    assert hass.states.get(f"fan.{UP}").state == STATE_UNAVAILABLE
    assert hass.states.get(f"sensor.{UP}_carbon_dioxide").state == STATE_UNAVAILABLE
    assert hass.states.get(f"binary_sensor.{UP}_online").state == STATE_OFF
    assert hass.states.get(f"sensor.{UP}_wi_fi_signal").state == "0"
    assert hass.states.get(f"fan.{DOWN}").state == STATE_ON


async def test_odd_unused_fields_do_not_break_the_poll(
    hass: HomeAssistant, setup_integration, group_json
) -> None:
    """Values in fields the integration does not use cannot fail the whole poll."""
    group_json["data"].update(target_temperature="", status=None, mode=None)
    group_json["data"]["devices"][1].update(has_filter="unknown", type=None)
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(f"fan.{DOWN}").attributes["percentage"] == 80


async def test_not_ready_on_server_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """Cloud down at start: retry later."""
    aioclient_mock.get(GROUP_URL, status=502)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_expiring_token_is_refreshed_and_saved(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    setup_integration,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A token near expiry is refreshed before the request and persisted."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_TOKENS: make_tokens(timedelta(days=1))}
    )
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE)
    await setup_integration()

    _method, url, form, _ = aioclient_mock.mock_calls[0]
    assert str(url).endswith("/oauth/token")
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "stored-refresh"
    _, _, _, headers = aioclient_mock.mock_calls[1]
    assert headers["Authorization"] == "Bearer new-access"
    assert config_entry.data[CONF_TOKENS]["refresh_token"] == "new-refresh"


async def test_revoked_tokens_start_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """401 and a dead refresh token: entry fails and asks to log in again."""
    aioclient_mock.get(GROUP_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == SOURCE_REAUTH for f in flows)


async def test_poll_failure_marks_unavailable(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failed poll makes entities unavailable instead of keeping stale data."""
    await setup_integration()
    aioclient_mock.clear_requests()
    aioclient_mock.get(GROUP_URL, status=503)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(f"fan.{DOWN}").state == STATE_UNAVAILABLE


async def test_diagnostics_redacted(hass: HomeAssistant, setup_integration) -> None:
    """No tokens, email or address in diagnostics."""
    entry = await setup_integration()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    for secret in ("stored-access", "stored-refresh", "user@example.com", "Testvej"):
        assert secret not in text
    assert diag["group"]["devices"][1]["comfort_level"] == 4


async def test_unload(hass: HomeAssistant, setup_integration) -> None:
    """Entry unloads cleanly."""
    entry = await setup_integration()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_unit_removed_from_account(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker, group_json
) -> None:
    """A unit that disappears from the account goes unavailable instead of erroring."""
    await setup_integration()
    group_json["data"]["devices"] = group_json["data"]["devices"][1:]
    aioclient_mock.clear_requests()
    aioclient_mock.get(GROUP_URL, json=group_json)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(f"fan.{UP}").state == STATE_UNAVAILABLE
    assert hass.states.get(f"sensor.{UP}_carbon_dioxide").state == STATE_UNAVAILABLE
    assert hass.states.get(f"fan.{DOWN}").state == STATE_ON


async def test_forbidden_group_does_not_loop_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """403 (login fine, no access to the home) retries later instead of asking to log in."""
    aioclient_mock.get(GROUP_URL, status=403)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()
