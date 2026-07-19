"""VerdiGrow integration constants."""

DOMAIN = "verdigrow"

# Config entry data
CONF_URL = "url"
CONF_TOKEN = "token"
CONF_VERIFY_SSL = "verify_ssl"

# Options
CONF_INTERVAL = "update_interval"      # seconds between pushes
DEFAULT_INTERVAL = 3600                # once per hour (don't flood the DB)

# Mapping target kinds (stored in HA; VerdiGrow only receives the resolved key)
TARGET_CONTAINER = "container"
TARGET_AREA = "area"
TARGET_PLANT = "plant"

# The sensor map lives in HA (this integration), NOT in VerdiGrow. Stored here.
STORAGE_KEY = "verdigrow_mappings"
STORAGE_VERSION = 1

# Custom sidebar panel (the tree/filter mapping UI ships inside this integration)
PANEL_URL = "verdigrow"
PANEL_TITLE = "VerdiGrow Link"
PANEL_ICON = "mdi:sprout"
STATIC_URL = "/verdigrow_static"

# VerdiGrow API paths — read-only catalog + readings ingest (token, Bearer)
API_PING = "/api/ping/"
API_CONTAINERS = "/api/containers/"
API_PLANTS = "/api/plants/"
API_AREAS = "/api/areas/"
API_AREAS_IMPORT = "/api/areas/import/"
API_AREAS_DELETE = "/api/areas/delete/"
API_METRIC_TYPES = "/api/metric-types/"
API_CARDS = "/api/cards/"
API_READINGS = "/api/readings/"
API_DEVICES = "/api/devices/"
API_DEVICE_MAP = "/api/devices/map/"
API_DEVICE_USAGE = "/api/device-usage/"
