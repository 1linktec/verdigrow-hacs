# VerdiGrow — Home Assistant integration

Connects [VerdiGrow](https://github.com/1linktec/verdigrow), the self-hosted
grower's record system, to Home Assistant. **HA stays the sensor hub and renders
the dashboards; VerdiGrow stores the grow records.** The integration:

- surfaces every VerdiGrow **container as a native HA device** (with a plants
  sensor, a sensor per metric, and a latest-photo image entity), placed on its HA
  area;
- ships a rich **custom Lovelace card** for a container or a plant;
- **pushes** your mapped HA sensor readings back into VerdiGrow on a schedule;
- keeps **areas in sync** between the two systems.

No hardware access, no dashboards rendered here — it reads HA states and serves
VerdiGrow data.

## Install (HACS custom repository)

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/1linktec/verdigrow-hacs`, category **Integration** → **Add**.
2. Install **VerdiGrow**, then **restart Home Assistant**.
3. Settings → Devices & Services → **Add Integration** → **VerdiGrow**.

## Configure

Add-integration dialog:

- **URL** — your VerdiGrow address (e.g. `https://verdigrow.thehopes.ca` or
  `http://<host>:8095`).
- **API token** — the `API_TOKEN` from your VerdiGrow `.env`.

Update frequency (seconds between sensor pushes, default **3600 = 1 hour**) is set
in the integration's **Configure** dialog.

## The VerdiGrow Link panel

Everything is managed from the **VerdiGrow Link** panel in the HA sidebar.

### Sensor mapping

A fold-out tree where you map HA sensor entities onto VerdiGrow metrics:

- Each **area** and **container** expands to its sensor-linkable **metrics**.
- Use the **HA area filter** at the top to narrow the sensor list to one HA area.
- A sensor on a **container** is **dedicated** (that container + its plantings); a
  sensor on an **area** is **ambient** — it fans out to every container currently
  in that area.
- Hit **Save mapping**. VerdiGrow stores the map; the integration pushes the mapped
  values on the schedule, and readings appear on the container/plant **charts**.

### Area sync

VerdiGrow areas map 1:1 to HA areas. The **Area sync** section reconciles them:

- **In HA, not in VerdiGrow** — tick which HA areas to **import** (all ticked by
  default) → **Import selected into VerdiGrow**.
- **In VerdiGrow, not in HA** — for each, **create it in HA**, **map it to an
  existing HA area**, or leave it out → **Save**.
- **🗑 Remove VerdiGrow areas** — walk back a sync: **remove** an area from
  VerdiGrow (the HA area is untouched, and any mapping is cleared). Blocked while
  the area still holds containers — move them first.

## Native entities & the custom card

After setup, each VerdiGrow container appears as an **HA device on its area**, with:

- a **plants** sensor (what's growing, with notes),
- a **sensor per metric** (latest reading),
- an **image** entity (latest photo).

Rows nest under their bed. Renaming or deleting a container in VerdiGrow, and
uninstalling the integration, all propagate to HA.

Add the **VerdiGrow** card to any dashboard (`custom:verdigrow-container-card`).
Its visual editor lets you pick an **area**, then a **container or plant** — no
auto-pick. The card shows the photo, planting chart, plants (with photos + notes),
and latest metrics.

> **Companion app showing "misconfigured" after an update?** From v0.12.0 the card
> and panel are version-stamped so updates bust the app's cache automatically. On
> an older install, do this once: Settings → Companion app → Troubleshooting →
> **Reset frontend cache**.

## License

[AGPL-3.0](LICENSE) © 2026 Jeff Hope
