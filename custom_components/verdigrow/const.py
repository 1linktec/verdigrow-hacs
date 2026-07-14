"""VerdiGrow integration constants."""

DOMAIN = "verdigrow"

CONF_URL = "url"
CONF_TOKEN = "token"

DEFAULT_SCAN_INTERVAL = 60

# Panel — VerdiGrow is embedded as an HTTPS iframe.
#
# NOTE: the Lovelace webpage card pointing at VerdiGrow must set
#   allow_open_top_navigation: true
# so the "Add photo" button can break out to Chrome. HA's Android WebView
# cannot open the camera from an HTML file input:
#   https://github.com/home-assistant/android/issues/6055
PANEL_URL_PATH = "verdigrow"
PANEL_TITLE = "VerdiGrow"
PANEL_ICON = "mdi:sprout"
