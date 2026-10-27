"""Data update coordinator for Air by Nature."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AirByNatureAuthError,
    AirByNatureClient,
    AirByNatureConnectionError,
    DeviceGroup,
)
from .const import DOMAIN, LOGGER, SCAN_INTERVAL

type AirByNatureConfigEntry = ConfigEntry[AirByNatureCoordinator]


class AirByNatureCoordinator(DataUpdateCoordinator[DeviceGroup]):
    """Polls one device group."""

    config_entry: AirByNatureConfigEntry
    # Device registry id of the home, the via device of each unit. Set by
    # async_setup_entry after the first refresh, before the platforms load.
    group_device_id: str

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AirByNatureConfigEntry,
        client: AirByNatureClient,
        group_id: int,
    ) -> None:
        """Initialise."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.group_id = group_id
        # Last non-zero level per unit, so turn_on restores it.
        self.last_on_level: dict[int, int] = {}

    async def _async_update_data(self) -> DeviceGroup:
        try:
            group = await self.client.get_group(self.group_id)
        except AirByNatureAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except AirByNatureConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        for device in group.devices.values():
            if device.comfort_level > 0:
                self.last_on_level[device.id] = device.comfort_level
        return group

    async def async_set_level(self, device_id: int, level: int) -> None:
        """Write a level and reflect it at once, without waiting for a poll."""
        try:
            stored = await self.client.set_comfort_level(self.group_id, device_id, level)
        except AirByNatureAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except AirByNatureConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if self.data and device_id in self.data.devices:
            self.data.devices[device_id].comfort_level = stored
            if stored > 0:
                self.last_on_level[device_id] = stored
            self.async_set_updated_data(self.data)
