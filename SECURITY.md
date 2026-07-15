# Security Policy

## Sensitive Data

Do not include real Kitafino credentials, cookies, account IDs, household data, raw Kitafino HTML, request bodies, response bodies, or Home Assistant secrets in issues, pull requests, logs, screenshots, fixtures, or diagnostics examples.

The test suite contains regression guardrails for public repository files and runtime projections such as diagnostics, entity attributes, logs, persisted snapshots, and MQTT payloads. Parser fixtures must be synthetic or sanitized before they are committed; preserve only the HTML structure needed for tests.

## Reporting A Security Issue

If the GitHub repository has private vulnerability reporting enabled, use that channel.

If private reporting is not available yet, open an issue without secrets or private data and describe the affected area at a high level. The maintainer can then arrange a safer follow-up channel.
