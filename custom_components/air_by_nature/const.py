"""Constants for the Air by Nature integration."""

import logging
from datetime import timedelta

DOMAIN = "air_by_nature"
LOGGER = logging.getLogger(__package__)

CONF_GROUP_ID = "group_id"
CONF_TOKENS = "tokens"

# Units report a new reading every 60 s.
SCAN_INTERVAL = timedelta(seconds=60)

# Level used by fan.turn_on when no earlier level is known (Normal).
DEFAULT_ON_LEVEL = 3

MANUFACTURER = "AIRbyNATURE"
