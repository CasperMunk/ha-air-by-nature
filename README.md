# Air by Nature for Home Assistant

Custom integration for AIRbyNATURE decentralised ventilation units, controlled through the same cloud API as [admin.airbynature.com](https://admin.airbynature.com).

Unofficial. AIRbyNATURE does not publish this API, so a change on their side can break the integration.

## What you get

Per ventilation unit:

| Entity | Notes |
| --- | --- |
| Fan | Off plus 5 speeds (20 % steps). `turn_on` restores the last speed, else Normal. |
| Select: Comfort level | Off, Very quiet, Quiet, Normal, High, Extra high (Danish names in a Danish UI). |
| Sensors | Supply and extract air temperature and humidity, outdoor temperature, CO2, VOC, supply and extract fan %. |
| Diagnostic | Online, drying heat exchanger, Wi-Fi signal, last reading, fan RPM (disabled by default). |

For the home, a device called **Ventilation system** (the units hang under it) with an **Active rule** sensor showing which schedule rule the cloud is running, with mode and status as attributes.

Readings and control entities go unavailable while a unit is offline; the Online sensor stays available so you can alert on it.

## Install

Requires Home Assistant 2026.8 or newer.

1. HACS → three dots → Custom repositories → add this repository as type *Integration*.
2. Install **Air by Nature**, restart Home Assistant.
3. Settings → Devices & services → Add integration → **Air by Nature**.
4. Log in with your admin.airbynature.com email and password.

The password is used once to get tokens and is not stored. If the cloud later rejects the tokens, Home Assistant asks for the password again.

## Remove

1. Settings → Devices & services → **Air by Nature** → three dots → **Delete**.
2. To remove the files too: HACS → **Air by Nature** → three dots → **Remove**, then restart Home Assistant.

Deleting the integration removes the stored tokens from Home Assistant. The units keep running at their last level and on the cloud schedule.

## Security

- Only OAuth tokens are stored, in Home Assistant's config entry storage. The password is never saved.
- `client_id` and `client_secret` in `api.py` are the public values of the AIRbyNATURE web app (they ship in its JavaScript). They identify the app, not you.
- All traffic goes over HTTPS to `admin.airbynature.com`. Nothing else is contacted.
- Diagnostics downloads redact tokens, email, home name and address.
- Report a vulnerability privately through GitHub's *Report a vulnerability* button on the Security tab, not in a public issue.

## How it works

- Polls `GET /api/user-app/devicegroups/{id}` every 60 s (units report once a minute).
- Speed changes `PATCH /api/user-app/devicegroups/{id}/devices/{unit}` with `{"comfort_level": 0-5}` and update HA immediately.
- OAuth2 password grant with the web app's public client; access tokens are refreshed a week before expiry, and once on any 401.

The API client (`api.py`) has no Home Assistant imports so it can become a separate package later.

## Known limits

- The cloud schedule can change the level on its own. Check **Active rule** if a speed you set changes back.
- Pause inlet, target temperature and schedule editing are not supported yet.
- The VOC unit is assumed to be ppb; the API does not state it.

## Development

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component ruff mypy pytest-cov
pytest --cov=custom_components.air_by_nature   # 100 % coverage
ruff check . && ruff format --check .           # includes bandit security rules
mypy custom_components/air_by_nature           # strict
```

CI also runs hassfest, the HACS validator, zizmor (workflow security) and the tests against both the oldest supported and the latest Home Assistant.
