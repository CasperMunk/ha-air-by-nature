"""Base entities for Air by Nature."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Device, DeviceGroup
from .const import DOMAIN, MANUFACTURER
from .coordinator import AirByNatureCoordinator

MODEL_NAMES = {
    "main-v2": "Main unit v2",
    "external-v2": "Wall unit v2",
}


def group_device_info(group: DeviceGroup) -> DeviceInfo:
    """Device info of the home, the parent device of its units.

    Named after the home as the cloud knows it, so it does not read like a
    duplicate of the integration.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, f"group_{group.id}")},
        manufacturer=MANUFACTURER,
        model="Home",
        name=group.name,
        configuration_url=f"https://admin.airbynature.com/app/{group.id}/overview",
    )


class AirByNatureDeviceEntity(CoordinatorEntity[AirByNatureCoordinator]):
    """Entity tied to one ventilation unit."""

    _attr_has_entity_name = True
    # Most entities are meaningless while the unit is offline.
    _requires_online = True

    def __init__(self, coordinator: AirByNatureCoordinator, device_id: int, key: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_{key}"
        device = coordinator.data.devices[device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            manufacturer=MANUFACTURER,
            model=MODEL_NAMES.get(device.type, device.type or None),
            name=device.name,
            via_device_id=coordinator.group_device_id,
        )

    @property
    def device(self) -> Device:
        """Current device state."""
        return self.coordinator.data.devices[self._device_id]

    @property
    def available(self) -> bool:
        """Available when polled, present, and (if required) online."""
        if not super().available:
            return False
        device = self.coordinator.data.devices.get(self._device_id)
        if device is None:
            return False
        return device.is_online or not self._requires_online


class AirByNatureGroupEntity(CoordinatorEntity[AirByNatureCoordinator]):
    """Entity tied to the device group (the home)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AirByNatureCoordinator, key: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self._attr_unique_id = f"group_{coordinator.group_id}_{key}"
        self._attr_device_info = group_device_info(coordinator.data)
