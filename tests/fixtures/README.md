# Fixture Policy

Fixtures must be synthetic or sanitized before they are committed.

Never commit:

- real Kitafino credentials
- cookies or tokens
- raw household HTML captures
- account IDs
- child-identifying data
- request bodies
- response bodies
- Home Assistant secrets

Use small synthetic HTML snippets that preserve only the structure needed by parser tests.
