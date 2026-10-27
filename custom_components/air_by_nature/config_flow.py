"""Config flow for Air by Nature."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AirByNatureAuthError,
    AirByNatureClient,
    AirByNatureError,
    Tokens,
)
from .const import CONF_GROUP_ID, CONF_TOKENS, DOMAIN, LOGGER

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


class AirByNatureConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in with the same email and password as admin.airbynature.com."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise."""
        self._username: str | None = None
        self._tokens: Tokens | None = None
        self._groups: list[dict[str, Any]] = []

    async def _login(
        self, username: str, password: str, *, list_groups: bool = False
    ) -> dict[str, str]:
        """Log in (and optionally list homes); return form errors, if any."""
        client = AirByNatureClient(async_get_clientsession(self.hass))
        try:
            self._tokens = await client.login(username, password)
            if list_groups:
                self._groups = await client.list_groups()
        except AirByNatureAuthError:
            return {"base": "invalid_auth"}
        except AirByNatureError:
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001 - HA convention: never crash the form
            LOGGER.exception("Unexpected error during login")
            return {"base": "unknown"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._login(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD], list_groups=True
            )
            if not errors:
                if not self._groups:
                    return self.async_abort(reason="no_groups")
                self._username = user_input[CONF_USERNAME]
                if len(self._groups) == 1:
                    return await self._create(int(self._groups[0]["id"]))
                return await self.async_step_group()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA,
                # Keep the email after an error, but never send the password back.
                {CONF_USERNAME: user_input[CONF_USERNAME]} if user_input else None,
            ),
            errors=errors,
        )

    async def async_step_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick a home when the account has several."""
        if user_input is not None:
            return await self._create(int(user_input[CONF_GROUP_ID]))
        options = [
            SelectOptionDict(value=str(g["id"]), label=str(g.get("name") or g["id"]))
            for g in self._groups
        ]
        return self.async_show_form(
            step_id="group",
            data_schema=vol.Schema(
                {vol.Required(CONF_GROUP_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def _create(self, group_id: int) -> ConfigFlowResult:
        await self.async_set_unique_id(str(group_id))
        self._abort_if_unique_id_configured()
        if self._tokens is None:  # pragma: no cover - set by a successful login
            return self.async_abort(reason="unknown")
        return self.async_create_entry(
            title="Air by Nature",
            data={
                CONF_USERNAME: self._username,
                CONF_GROUP_ID: group_id,
                CONF_TOKENS: self._tokens.as_dict(),
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Tokens stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._login(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if not errors and self._tokens is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_TOKENS: self._tokens.as_dict()},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD, autocomplete="current-password"
                        )
                    )
                }
            ),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )
