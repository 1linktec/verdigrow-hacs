# VerdiGrow — Home Assistant Integration

Companion integration for [VerdiGrow](https://github.com/1linktec/verdigrow), a
self-hosted grower's record system built on the tagged container as the atom.

## What it does

Surfaces your VerdiGrow containers into Home Assistant as native entities, so you can
build area dashboards that combine plant data with your existing cameras, irrigation
switches and sensors.

Per container:

- Current plant (variety + sow date)
- Days since sow · days to maturity countdown
- Latest metric values
- Needs-attention flag
- Latest photo
- Link into the VerdiGrow panel

Plus a **VerdiGrow panel** — the app embedded as an HTTPS iframe for daily interaction.

## Install

HACS → ⋮ → Custom repositories → add `https://github.com/1linktec/verdigrow-hacs`
(category: Integration) → Install → restart HA.

Then: Settings → Devices & Services → Add Integration → VerdiGrow. Provide your
VerdiGrow URL and API token (generate it in the VerdiGrow console).

## Requirements

- A running [VerdiGrow](https://github.com/1linktec/verdigrow) instance
- **Served over HTTPS** — HA won't embed HTTP content into an HTTPS page

## ⚠️ Photos

HA's Android Companion app [cannot open the camera from an HTML file input](https://github.com/home-assistant/android/issues/6055) —
open since Nov 2025. VerdiGrow works around it: set `allow_open_top_navigation: true`
on your webpage card and the "Add photo" button breaks out to Chrome, where the camera
works. Container and plant context ride in the URL.

```yaml
type: iframe
url: https://verdigrow.local/panel
allow_open_top_navigation: true   # required for photo capture
```

This will be removed when the upstream bug is fixed.

## License

[AGPL-3.0](LICENSE) © 2026 Jeff Hope
