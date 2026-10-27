"""Sensor platform for Air by Nature."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_BILLION,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import Device, DeviceGroup
from .coordinator import AirByNatureConfigEntry, AirByNatureCoordinator
from .entity import AirByNatureDeviceEntity, AirByNatureGroupEntity

PARALLEL_UPDATES = 0  # read-only, coordinator does the polling


def _reading(key: str) -> Callable[[Device], Any]:
    def get(device: Device) -> Any:
        return device.reading.get(key) if device.reading else None

    return get


def _timestamp(device: Device) -> datetime | None:
    raw = device.reading.get("created_at") if device.reading else None
    return dt_util.parse_datetime(raw) if isinstance(raw, str) else None


@dataclass(frozen=True, kw_only=True)
class DeviceSensorDescription(SensorEntityDescription):
    """Describes a per-unit sensor."""

    value_fn: Callable[[Device], Any]


def _temperature(key: str, api_key: str) -> DeviceSensorDescription:
    return DeviceSensorDescription(
        key=key,
        value_fn=_reading(api_key),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    )


def _humidity(key: str, api_key: str) -> DeviceSensorDescription:
    return DeviceSensorDescription(
        key=key,
        value_fn=_reading(api_key),
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    )


def _fan_percentage(key: str, api_key: str) -> DeviceSensorDescription:
    return DeviceSensorDescription(
        key=key,
        value_fn=_reading(api_key),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _fan_rpm(key: str, api_key: str) -> DeviceSensorDescription:
    return DeviceSensorDescription(
        key=key,
        value_fn=_reading(api_key),
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )


# "inlet" = supply air blown into the house, "outlet" = extract air from rooms.
DEVICE_SENSORS: tuple[DeviceSensorDescription, ...] = (
    _temperature("supply_temperature", "inlet_temp"),
    _humidity("supply_humidity", "inlet_humid"),
    _temperature("extract_temperature", "outlet_temp"),
    _humidity("extract_humidity", "outlet_humid"),
    _temperature("outdoor_temperature", "external_temp"),
    DeviceSensorDescription(
        key="co2",
        value_fn=_reading("outlet_co2"),
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    DeviceSensorDescription(
        key="tvoc",
        value_fn=_reading("outlet_tvoc"),
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_BILLION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    _fan_percentage("supply_fan", "inlet_fan"),
    _fan_percentage("extract_fan", "outlet_fan"),
    _fan_rpm("supply_fan_rpm", "inlet_fan1_rpm"),
    _fan_rpm("extract_fan_rpm", "outlet_fan1_rpm"),
    DeviceSensorDescription(
        key="wifi_signal",
        value_fn=lambda d: d.wifi_signal,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DeviceSensorDescription(
        key="last_reading",
        value_fn=_timestamp,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

# These still mean something while the unit is offline.
OFFLINE_OK = {"wifi_signal", "last_reading"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirByNatureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        AirByNatureDeviceSensor(coordinator, device_id, description)
        for device_id in coordinator.data.devices
        for description in DEVICE_SENSORS
    ]
    entities.append(AirByNatureActiveRuleSensor(coordinator))
    async_add_entities(entities)


class AirByNatureDeviceSensor(AirByNatureDeviceEntity, SensorEntity):
    """Per-unit sensor."""

    entity_description: DeviceSensorDescription

    def __init__(
        self,
        coordinator: AirByNatureCoordinator,
        device_id: int,
        description: DeviceSensorDescription,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._requires_online = description.key not in OFFLINE_OK

    @property
    def native_value(self) -> Any:
        """Current value."""
        return self.entity_description.value_fn(self.device)


class AirByNatureActiveRuleSensor(AirByNatureGroupEntity, SensorEntity):
    """Schedule rule the cloud is running now (explains level changes)."""

    _attr_translation_key = "active_rule"

    def __init__(self, coordinator: AirByNatureCoordinator) -> None:
        """Initialise."""
        super().__init__(coordinator, "active_rule")

    @property
    def native_value(self) -> str | None:
        """Rule name, as named in the app."""
        group: DeviceGroup = self.coordinator.data
        return group.current_running_rule

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Group-level context."""
        group: DeviceGroup = self.coordinator.data
        return {
            "rule_enabled": group.is_rule_enabled,
            "mode": group.mode,
            "status": group.status,
        }
