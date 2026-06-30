"""Tests for MQTT scaffold import safety."""

from __future__ import annotations


def test_mqtt_scaffold_imports() -> None:
    from custom_components.speiseplan.mqtt import async_publish_snapshot

    assert async_publish_snapshot.__name__ == "async_publish_snapshot"
