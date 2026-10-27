"""Fan platform: one fan per ventilation unit, off plus 5 speeds."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .api import MAX_LEVEL
from .const import DEFAULT_ON_LEVEL
from .coordinator import AirByNatureConfigEntry, AirByNatureCoordinator
from .entity import AirByNatureDeviceEntity

SPEED_RANGE = (1, MAX_LEVEL)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirByNatureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up fans."""
    coordinator = entry.runtime_data
    async_add_entities(
        AirByNatureFan(coordinator, device_id) for device_id in coordinator.data.devices
    )


class AirByNatureFan(AirByNatureDeviceEntity, FanEntity):
    """Ventilation unit as a fan. Speed 1-5 maps to comfort level 1-5."""

    _attr_name = None  # main feature: entity takes the device name
    _attr_translation_key = "ventilation"
    _attr_speed_count = MAX_LEVEL
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: AirByNatureCoordinator, device_id: int) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id, "fan")

    @property
    def is_on(self) -> bool:
        """On when level is above 0."""
        return self.device.comfort_level > 0

    @property
    def percentage(self) -> int:
        """Level as a percentage (20 % steps)."""
        level = self.device.comfort_level
        return ranged_value_to_percentage(SPEED_RANGE, level) if level else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw level for templates and automations."""
        return {"comfort_level": self.device.comfort_level}

    async def async_set_percentage(self, percentage: int) -> None:
        """Set speed; 0 turns the unit off."""
        level = (
            0 if percentage == 0 else math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        )
        await self.coordinator.async_set_level(self._device_id, level)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on at the given speed, else the last speed, else Normal."""
        if percentage is not None:
            await self.async_set_percentage(percentage)
            return
        level = self.coordinator.last_on_level.get(self._device_id, DEFAULT_ON_LEVEL)
        await self.coordinator.async_set_level(self._device_id, level)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off (level 0)."""
        await self.coordinator.async_set_level(self._device_id, 0)
