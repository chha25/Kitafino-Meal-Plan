"""Constants for the Speiseplan integration."""

DOMAIN = "speiseplan"
DEFAULT_TITLE = "Kitafino Meal Plan"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CHILD_SLUG = "child_slug"

OPTION_CHILDREN = "children"
OPTION_CHILDREN_TEXT = "children_text"
OPTION_UPDATE_TIME = "update_time"
OPTION_MQTT_ENABLED = "mqtt_enabled"
OPTION_SHARED_SOURCE = "shared_source"

DEFAULT_UPDATE_TIME = "06:00"
DEFAULT_MQTT_ENABLED = False
DEFAULT_SHARED_SOURCE = True

CHILD_SLUG_MAX_LENGTH = 32
CHILD_SLUG_RESERVED = frozenset({"shared"})

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")
SHARED_CURRENT_ENTITY_ID_TEMPLATE = "sensor.speiseplan_shared_current_{weekday}"
CHILD_CURRENT_ENTITY_ID_TEMPLATE = "sensor.speiseplan_{slug}_current_{weekday}"

FORBIDDEN_SECRET_MARKERS = (
    "REAL_KITAFINO_PASSWORD_VALUE",
    "REAL_SESSION_COOKIE_VALUE",
    "RAW_KITAFINO_HTML_CAPTURE",
    "REAL_ACCOUNT_ID_VALUE",
)
