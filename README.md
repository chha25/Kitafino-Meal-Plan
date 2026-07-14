# Kitafino Meal Plan

Kitafino Meal Plan is a Home Assistant custom integration for showing Kitafino meal-plan data as native Home Assistant entities.

## Status

This repository is in early implementation. The MVP target is:

- HACS custom repository installation
- Home Assistant minimum version `2026.6.4`
- Initial Home Assistant UI credential setup
- Child, schedule, reauth, and MQTT option surfaces in later stories
- Shared-source Current Week meal sensors first
- Child-specific sensors deferred until reliable Kitafino evidence exists
- Next Week support deferred until reliable Kitafino evidence exists
- Secure handling of credentials, cookies, diagnostics, fixtures, and examples

The integration scaffold, configuration flow, Kitafino retrieval/parsing core, stale snapshot handling, manual refresh service, and shared Current Week sensor projection are in place. Runtime wiring will continue to mature through the remaining stories.

## Shared Source and Child Labels

Child labels are metadata in the MVP. They help preserve household context in configuration and diagnostics, but they do not mean Kitafino has provided child-specific meals.

Child-specific meal sensors are deferred until reliable Kitafino evidence exists. Until then, the integration exposes shared-source Current Week meal sensors and marks shared-source state explicitly in sensor attributes.

Next Week support is deferred until Kitafino exposes it reliably enough to test. Current Week sensors do not depend on Next Week data, and missing or inconsistent Next Week source data should not make Current Week sensors unavailable.

## Entities and Attributes

The MVP exposes one health sensor and one shared Current Week meal sensor per weekday:

- `sensor.speiseplan_health`
- `sensor.speiseplan_shared_current_{weekday}` where `{weekday}` is `monday`, `tuesday`, `wednesday`, `thursday`, or `friday`

Meal sensor state is the sanitized meal text for that weekday. Missing Current Week meal data makes the weekday sensor unavailable instead of inventing a value.

Meal sensor attributes are stable and non-secret:

- `child_key`
- `week_kind`
- `iso_year`
- `iso_week`
- `weekday`
- `source_date`
- `last_successful_update`
- `stale`
- `shared_source`

The health sensor state is one of the integration health values such as `ok`, `stale`, `login_failed`, `network_error`, `parse_error`, or `unknown_error`. Health attributes include `last_successful_update`, `last_error`, `configured_child_count`, `shared_source`, `parser_version`, and `fetched_at`.

Entity states, attributes, diagnostics, and examples must not contain Kitafino credentials, cookies, raw HTML, raw request/response bodies, or account identifiers.

## Optional MQTT Publishing

MQTT publishing is disabled by default. When enabled in the integration options, Speiseplan publishes sanitized snapshot-derived payloads through Home Assistant's existing MQTT integration. The integration does not store or request separate broker credentials.

Published topics use the stable prefix `speiseplan/{entry_id}`:

- `speiseplan/{entry_id}/snapshot`
- `speiseplan/{entry_id}/health`
- `speiseplan/{entry_id}/meal/{source}/{week}/{day}`

For the MVP shared-source meal plan, `{source}` is `shared`, `{week}` is `current`, and `{day}` is one of `monday`, `tuesday`, `wednesday`, `thursday`, or `friday`. Topic segments are sanitized before publication.

MQTT messages are published with QoS `0` and retained messages disabled.

Snapshot payload shape:

```json
{
  "health": {
    "state": "ok",
    "last_error": null,
    "last_successful_update": "2026-07-14T06:00:00+02:00",
    "fetched_at": "2026-07-14T06:00:00+02:00",
    "shared_source": true,
    "parser_version": "kitafino-html-v1"
  },
  "fetched_at": "2026-07-14T06:00:00+02:00",
  "last_successful_update": "2026-07-14T06:00:00+02:00",
  "shared_source": true,
  "parser_version": "kitafino-html-v1",
  "configured_child_count": 1,
  "entries": []
}
```

Health payload shape:

```json
{
  "state": "ok",
  "last_error": null,
  "last_successful_update": "2026-07-14T06:00:00+02:00",
  "fetched_at": "2026-07-14T06:00:00+02:00",
  "shared_source": true,
  "parser_version": "kitafino-html-v1"
}
```

Meal payload shape:

```json
{
  "source": "shared",
  "week": "current",
  "day": "monday",
  "meal_text": "Pasta",
  "source_date": "2026-07-14",
  "fetched_at": "2026-07-14T06:00:00+02:00",
  "stale": false,
  "shared_source": true,
  "iso_year": 2026,
  "iso_week": 29
}
```

Payloads must not contain Kitafino username, password, cookies, tokens, raw HTML, raw request/response bodies, diagnostic dumps, sensitive headers, account IDs, or child display names. Known unsafe values are redacted before publication.

## Installation

1. Add this repository as a HACS custom repository of type `Integration`.
2. Install the Speiseplan integration through HACS.
3. Restart Home Assistant if HACS asks for it.
4. Add the integration through the Home Assistant UI and enter your Kitafino credentials.

## Repository Setup

Repository URL: https://github.com/chha25/Kitafino-Meal-Plan

## Security

Do not commit real Kitafino credentials, cookies, account IDs, household data, raw Kitafino HTML, request bodies, or response bodies.

Examples must use placeholders such as `<kitafino_username>` and `<kitafino_password>`.

## Development

Install development dependencies with:

```bash
python -m pip install -r requirements-dev.txt
```

Run tests with:

```bash
python -m pytest
```

The current scaffold keeps runtime code import-safe and avoids network access during import.

GitHub Actions runs the same test command on pushes to `main` and pull requests.

## License

MIT. See [LICENSE](LICENSE).
