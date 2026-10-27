"""The Air by Nature integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AirByNatureClient, Tokens
from .const import CONF_GROUP_ID, CONF_TOKENS
from .coordinator import AirByNatureConfigEntry, AirByNatureCoordinator
from .entity import group_device_info

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.FAN,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: AirByNatureConfigEntry) -> bool:
    """Set up Air by Nature from a config entry."""
    client = AirByNatureClient(
        async_get_clientsession(hass), Tokens.from_dict(entry.data[CONF_TOKENS])
    )

    @callback
    def _persist_tokens(tokens: Tokens) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKENS: tokens.as_dict()}
        )

    client.add_token_listener(_persist_tokens)

    group_id = int(entry.data[CONF_GROUP_ID])
    # The home is the parent device of each unit; create it before the units.
    group_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **group_device_info(group_id)
    )

    coordinator = AirByNatureCoordinator(hass, entry, client, group_id, group_device.id)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AirByNatureConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
