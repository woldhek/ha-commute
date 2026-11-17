"""Constants of the Commute integration."""

DOMAIN = "commute"

CONF_NAME = "name"
CONF_PERSON = "person"
CONF_HOME_ZONE = "home_zone"
CONF_WORK_ZONE = "work_zone"
CONF_WORK_DAYS = "work_days"
CONF_VEHICLE = "vehicle"
CONF_ACTIVITY = "activity_sensor"
CONF_NS_TO_WORK = "ns_to_work"
CONF_NS_TO_HOME = "ns_to_home"
CONF_NS_TRACKER = "ns_tracker"

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_WORK_DAYS = ["mon", "tue", "wed", "thu", "fri"]

STORAGE_VERSION = 1
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
