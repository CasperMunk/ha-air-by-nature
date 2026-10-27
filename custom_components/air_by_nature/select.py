"""Select platform: comfort level by name (Slukket ... Ekstra høj)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import LEVEL_KEYS
from .coordinator import AirByNatureConfigEntry, AirByNatureCoordinator
from .entity import AirByNatureDeviceEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirByNatureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        AirByNatureLevelSelect(coordinator, device_id) for device_id in coordinator.data.devices
    )


class AirByNatureLevelSelect(AirByNatureDeviceEntity, SelectEntity):
    """Comfort level with the app's own names."""

    _attr_translation_key = "comfort_level"
    _attr_options = list(LEVEL_KEYS)

    def __init__(self, coordinator: AirByNatureCoordinator, device_id: int) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id, "comfort_level")

    @property
    def current_option(self) -> str | None:
        """Current level name."""
        level = self.device.comfort_level
        return LEVEL_KEYS[level] if 0 <= level < len(LEVEL_KEYS) else None

    async def async_select_option(self, option: str) -> None:
        """Set level by name."""
        await self.coordinator.async_set_level(self._device_id, LEVEL_KEYS.index(option))
