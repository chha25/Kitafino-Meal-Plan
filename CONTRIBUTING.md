# Contributing

## Local Setup

Create and activate a virtual environment, then install the development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the test suite with:

```bash
python -m pytest
```

## Fixture And Secret Policy

Do not commit real Kitafino credentials, cookies, account IDs, household data, raw Kitafino HTML, request bodies, or response bodies.

Fixtures must be synthetic or fully sanitized. If a test needs Kitafino-like HTML, keep the structure realistic enough for parser coverage but remove all real names, IDs, tokens, meals tied to a household, and provider-specific private data.

## Scope

This repository is currently in early implementation. Keep changes aligned with the story files under `_bmad-output/implementation-artifacts/` when they exist.
