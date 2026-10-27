"""Diagnostics for Air by Nature."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_TOKENS
from .coordinator import AirByNatureConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_TOKENS,
    "name",
    "address",
    "postcode",
    "city",
    "serial_number",
    "config",
    # Not in responses seen so far; redacted in case other accounts include them.
    "email",
    "phone",
    "latitude",
    "longitude",
    "mac",
    "mac_address",
    "ip",
    "ip_address",
    "users",
    "owner",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AirByNatureConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and the last raw API response."""
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "group": async_redact_data(entry.runtime_data.data.raw, TO_REDACT),
    }
