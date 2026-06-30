# Kitafino Meal Plan

Kitafino Meal Plan is a Home Assistant custom integration for showing Kitafino meal-plan data as native Home Assistant entities.

## Status

This repository is in early implementation. The MVP target is:

- HACS custom repository installation
- Home Assistant minimum version `2026.6.4`
- Home Assistant UI configuration in later stories
- Shared-source Current Week meal sensors first
- Child-specific sensors deferred until reliable Kitafino evidence exists
- Next Week support deferred until reliable Kitafino evidence exists
- Secure handling of credentials, cookies, diagnostics, fixtures, and examples

The integration scaffold is in place. Runtime Kitafino login, credential validation, meal parsing, real Home Assistant entities, and optional MQTT publishing are implemented in later stories.

## Installation

1. Add this repository as a HACS custom repository of type `Integration`.
2. Install the Speiseplan integration through HACS.
3. Restart Home Assistant if HACS asks for it.
4. Add the integration through the Home Assistant UI after config-flow implementation is complete.

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
