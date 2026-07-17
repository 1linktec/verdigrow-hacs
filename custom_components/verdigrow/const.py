"""VerdiGrow integration constants."""

DOMAIN = "verdigrow"

# Config entry data
CONF_URL = "url"
CONF_TOKEN = "token"
CONF_VERIFY_SSL = "verify_ssl"

# Options
CONF_INTERVAL = "update_interval"      # seconds between pushes
DEFAULT_INTERVAL = 3600                # once per hour (don't flood the DB)
CONF_MAPPINGS = "mappings"             # list of {entity_id, target, id, metric}
CONF_AREA_LINKS = "area_links"         # list of {ha_area_id, ha_area_name, targets[]}

# Mapping target kinds
TARGET_CONTAINER = "container"
TARGET_AREA = "area"
TARGET_PLANT = "plant"

# VerdiGrow API paths (token-authenticated, Bearer)
API_PING = "/api/ping/"
API_CONTAINERS = "/api/containers/"
API_PLANTS = "/api/plants/"
API_AREAS = "/api/areas/"
API_METRIC_TYPES = "/api/metric-types/"
API_READINGS = "/api/readings/"
