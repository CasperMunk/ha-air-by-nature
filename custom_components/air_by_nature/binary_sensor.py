"""Binary sensor platform for Air by Nature."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Device
from .coordinator import AirByNatureConfigEntry, AirByNatureCoordinator
from .entity import AirByNatureDeviceEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DeviceBinaryDescription(BinarySensorEntityDescription):
    """Describes a per-unit binary sensor."""

    value_fn: Callable[[Device], bool]
    requires_online: bool = True


BINARY_SENSORS: tuple[DeviceBinaryDescription, ...] = (
    DeviceBinaryDescription(
        key="online",
        value_fn=lambda d: d.is_online,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        requires_online=False,
    ),
    DeviceBinaryDescription(
        key="drying_heat_exchanger",
        value_fn=lambda d: d.is_drying_heat_exchanger,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirByNatureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        AirByNatureBinarySensor(coordinator, device_id, description)
        for device_id in coordinator.data.devices
        for description in BINARY_SENSORS
    )


class AirByNatureBinarySensor(AirByNatureDeviceEntity, BinarySensorEntity):
    """Per-unit binary sensor."""

    entity_description: DeviceBinaryDescription

    def __init__(
        self,
        coordinator: AirByNatureCoordinator,
        device_id: int,
        description: DeviceBinaryDescription,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._requires_online = description.requires_online

    @property
    def is_on(self) -> bool:
        """Current state."""
        return self.entity_description.value_fn(self.device)
