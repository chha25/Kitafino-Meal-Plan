# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-07-19

### Added

- HACS-compatible Home Assistant custom integration packaging.
- UI configuration, options, reauthentication, and reconfiguration flows.
- Shared Current Week meal sensors for Monday through Friday.
- Health sensor with freshness attributes and stale snapshot recovery.
- Configurable update schedule and throttled manual refresh service.
- Optional sanitized MQTT snapshot, health, and meal publishing.
- Redacted diagnostics and operational failure classification.
- Parsing for the currently observed Kitafino structure, returning one selected meal per weekday.
- Parser strategy `kitafino-html-v2` with legacy fixture compatibility.
- Authentication through the dedicated Kitafino authentication and user endpoints.

### Fixed

- Corrected the Kitafino meal-plan endpoint.
- Reconciled conflicting parent-domain and user-host `PHPSESSID` cookies.
- Distinguished network, authentication, and parser failures without exposing response content.

### Security

- Credentials are stored by Home Assistant in config-entry data and excluded from logs, diagnostics, and public outputs.
- Session cookies remain memory-only and are never logged or persisted.
- Diagnostics, MQTT payloads, fixtures, and repository examples exclude raw HTML, account identifiers, and sensitive HTTP data.
- Local investigation material under `.private/` is excluded from version control.

[Unreleased]: https://github.com/chha25/Kitafino-Meal-Plan/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/chha25/Kitafino-Meal-Plan/releases/tag/v1.0.0
