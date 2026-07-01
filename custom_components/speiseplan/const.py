"""Constants for the Speiseplan integration."""

DOMAIN = "speiseplan"
DEFAULT_TITLE = "Kitafino Meal Plan"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")
SHARED_CURRENT_ENTITY_ID_TEMPLATE = "sensor.speiseplan_shared_current_{weekday}"

FORBIDDEN_SECRET_MARKERS = (
    "REAL_KITAFINO_PASSWORD_VALUE",
    "REAL_SESSION_COOKIE_VALUE",
    "RAW_KITAFINO_HTML_CAPTURE",
    "REAL_ACCOUNT_ID_VALUE",
)
