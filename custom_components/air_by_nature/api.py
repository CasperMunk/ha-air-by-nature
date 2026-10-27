"""Async client for the Air by Nature cloud API.

Standalone on purpose: no Home Assistant imports, so it can move to its own
PyPI package later without changes.

API facts (verified against admin.airbynature.com, 27 Oct 2026):
- Laravel Passport OAuth2, password grant, public SPA client.
- GET  /api/user-app/devicegroups                     list of {id, name}
- GET  /api/user-app/devicegroups/{group}             group with devices
- PATCH /api/user-app/devicegroups/{group}/devices/{id}  {"comfort_level": 0-5}
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

BASE_URL = "https://admin.airbynature.com"
TOKEN_PATH = "/oauth/token"  # noqa: S105 - a URL path, not a secret
USER_APP_PATH = "/api/user-app"

# Public client of the Angular web app (same values ship in its JS bundle).
CLIENT_ID = "1"
CLIENT_SECRET = "angular-app"  # noqa: S105 - public, see above
SCOPE = "*"

# Refresh this long before the access token expires.
REFRESH_MARGIN = timedelta(days=7)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

MIN_LEVEL = 0
MAX_LEVEL = 5

# Order matters: index == comfort_level. Names from the web app source.
LEVEL_KEYS: tuple[str, ...] = (
    "off",  # Slukket
    "very_quiet",  # Meget stille
    "quiet",  # Stille
    "normal",  # Normal
    "high",  # Høj
    "extra_high",  # Ekstra høj
)


class AirByNatureError(Exception):
    """Base error."""


class AirByNatureAuthError(AirByNatureError):
    """Credentials or tokens rejected."""


class AirByNatureConnectionError(AirByNatureError):
    """Network problem or unexpected server response."""


@dataclass
class Tokens:
    """OAuth tokens plus absolute expiry and planned refresh time."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    refresh_at: datetime

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> Tokens:
        """Build from a Passport token response."""
        try:
            access_token = str(data["access_token"])
            refresh_token = str(data["refresh_token"])
            lifetime = timedelta(seconds=int(data["expires_in"]))
        except (KeyError, TypeError, ValueError, OverflowError) as err:
            raise AirByNatureConnectionError("Malformed token response") from err
        if lifetime <= timedelta(0):
            raise AirByNatureConnectionError("Token response has no lifetime")
        now = datetime.now(UTC)
        # A week early, or halfway for short-lived tokens, so a short lifetime
        # does not cause a refresh on every request.
        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=now + lifetime,
            refresh_at=now + lifetime - min(REFRESH_MARGIN, lifetime / 2),
        )

    def as_dict(self) -> dict[str, str]:
        """Serialise for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "refresh_at": self.refresh_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Tokens:
        """Restore from storage."""
        expires_at = datetime.fromisoformat(data["expires_at"])
        refresh_at = data.get("refresh_at")
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at,
            refresh_at=(
                datetime.fromisoformat(refresh_at) if refresh_at else expires_at - REFRESH_MARGIN
            ),
        )

    def needs_refresh(self) -> bool:
        """True when the access token is due for a refresh."""
        return datetime.now(UTC) >= self.refresh_at


@dataclass
class Device:
    """One ventilation unit."""

    id: int
    name: str
    type: str
    comfort_level: int
    is_online: bool
    wifi_signal: int | None
    is_drying_heat_exchanger: bool
    # Latest sensor reading, keys as the API sends them; None before the first one.
    reading: dict[str, Any] | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Device:
        """Parse a device object."""
        history = data.get("latest_history")
        wifi = data.get("wifi_signal")
        return cls(
            id=int(data["id"]),
            name=str(data.get("name") or f"Unit {data['id']}"),
            type=str(data.get("type") or ""),
            comfort_level=min(max(int(data.get("comfort_level") or 0), MIN_LEVEL), MAX_LEVEL),
            is_online=bool(data.get("is_online")),
            wifi_signal=int(wifi) if wifi is not None else None,
            is_drying_heat_exchanger=bool(data.get("is_drying_heat_exchanger")),
            reading=history if isinstance(history, dict) else None,
        )


@dataclass
class DeviceGroup:
    """A home with one or more units."""

    id: int
    name: str
    mode: str | None
    current_running_rule: str | None
    is_rule_enabled: bool
    status: str | None
    devices: dict[int, Device]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DeviceGroup:
        """Parse a device group object."""
        devices = [Device.from_api(d) for d in data.get("devices") or []]
        return cls(
            id=int(data["id"]),
            name=str(data.get("name") or f"Group {data['id']}"),
            mode=data.get("mode"),
            current_running_rule=data.get("current_running_rule"),
            is_rule_enabled=bool(data.get("is_rule_enabled")),
            status=data.get("status"),
            devices={d.id: d for d in devices},
            raw=data,
        )


class AirByNatureClient:
    """Thin async client. Caller owns the aiohttp session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        """Initialise."""
        self._session = session
        self._base = base_url.rstrip("/")
        self.tokens = tokens
        self._token_listeners: list[Callable[[Tokens], None]] = []
        # One refresh at a time: Passport rotates the refresh token, so a second
        # concurrent refresh would send an already used token and fail.
        self._token_lock = asyncio.Lock()

    def add_token_listener(self, callback: Callable[[Tokens], None]) -> None:
        """Call `callback(tokens)` whenever tokens change, to persist them."""
        self._token_listeners.append(callback)

    def _set_tokens(self, tokens: Tokens) -> None:
        self.tokens = tokens
        for callback in self._token_listeners:
            callback(tokens)

    # Auth -----------------------------------------------------------------

    async def login(self, username: str, password: str) -> Tokens:
        """Password grant. Does not keep the password."""
        tokens = await self._token_request(
            {
                "grant_type": "password",
                "username": username,
                "password": password,
            }
        )
        self._set_tokens(tokens)
        return tokens

    async def refresh(self) -> Tokens:
        """Refresh grant."""
        async with self._token_lock:
            return await self._refresh()

    async def _refresh(self) -> Tokens:
        if self.tokens is None:
            raise AirByNatureAuthError("No tokens to refresh")
        tokens = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": self.tokens.refresh_token,
            }
        )
        self._set_tokens(tokens)
        return tokens

    async def _token_request(self, form: dict[str, str]) -> Tokens:
        payload = {
            **form,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": SCOPE,
        }
        try:
            async with self._session.post(
                self._base + TOKEN_PATH,
                data=payload,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
                # Never re-send the password to wherever a redirect points.
                allow_redirects=False,
            ) as resp:
                if resp.status in (400, 401):
                    # 400 invalid_grant: wrong credentials or dead refresh token
                    raise AirByNatureAuthError(f"Token request rejected ({resp.status})")
                if resp.status != 200:
                    raise AirByNatureConnectionError(f"Token endpoint returned {resp.status}")
                return Tokens.from_response(await resp.json())
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise AirByNatureConnectionError(str(err) or type(err).__name__) from err

    async def _ensure_token(self, rejected: str | None = None) -> str:
        """Return a usable access token, refreshing it if due or `rejected`.

        Concurrent callers wait on the lock and then reuse the token the first
        caller fetched, instead of refreshing again.
        """
        async with self._token_lock:
            if self.tokens is None:
                raise AirByNatureAuthError("Not logged in")
            if self.tokens.needs_refresh() or self.tokens.access_token == rejected:
                return (await self._refresh()).access_token
            return self.tokens.access_token

    # Requests -------------------------------------------------------------

    async def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        rejected: str | None = None
        while True:
            token = await self._ensure_token(rejected)
            try:
                async with self._session.request(
                    method,
                    self._base + USER_APP_PATH + path,
                    json=json,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=False,
                ) as resp:
                    if resp.status == 401 and rejected is None:
                        # Token revoked early: refresh once, then retry.
                        rejected = token
                        continue
                    if resp.status == 401:
                        raise AirByNatureAuthError(f"{method} {path}: {resp.status}")
                    # 403 means no access to this resource while the login still
                    # works; asking for the password again would not fix it.
                    if not 200 <= resp.status < 300:
                        raise AirByNatureConnectionError(f"{method} {path}: HTTP {resp.status}")
                    body = await resp.json()
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise AirByNatureConnectionError(str(err) or type(err).__name__) from err
            if not isinstance(body, dict) or "data" not in body:
                raise AirByNatureConnectionError(f"{method} {path}: unexpected body")
            return body["data"]

    async def list_groups(self) -> list[dict[str, Any]]:
        """Groups the user can access: [{id, name}]."""
        data = await self._request("GET", "/devicegroups")
        if not isinstance(data, list) or not all(
            isinstance(group, dict) and "id" in group for group in data
        ):
            raise AirByNatureConnectionError("Malformed group list")
        return data

    async def get_group(self, group_id: int) -> DeviceGroup:
        """Full state of one group."""
        data = await self._request("GET", f"/devicegroups/{group_id}")
        try:
            return DeviceGroup.from_api(data)
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise AirByNatureConnectionError("Malformed group response") from err

    async def set_comfort_level(self, group_id: int, device_id: int, level: int) -> int:
        """Set a unit's comfort level (0 off, 1-5). Returns the stored level."""
        if not MIN_LEVEL <= level <= MAX_LEVEL:
            raise ValueError(f"Level must be {MIN_LEVEL}-{MAX_LEVEL}, got {level}")
        data = await self._request(
            "PATCH",
            f"/devicegroups/{group_id}/devices/{device_id}",
            json={"comfort_level": level},
        )
        stored = data.get("comfort_level") if isinstance(data, dict) else None
        if isinstance(stored, int) and MIN_LEVEL <= stored <= MAX_LEVEL:
            return stored
        return level
