# VerdiGrow — Home Assistant integration

Push Home Assistant sensor readings into [VerdiGrow](https://github.com/1linktec/verdigrow),
the self-hosted grower's record system. **HA stays the sensor hub; VerdiGrow just
stores the metrics.** You choose which HA sensors map to which VerdiGrow container
or area, and this integration pushes their values on a schedule (default: once
per hour).

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

Then open the integration's **Configure**:

- **Update frequency** — seconds between pushes (default **3600 = 1 hour**; keeps
  the database from filling up).
- **Add a sensor mapping** — pick an HA sensor, the VerdiGrow **container** or
  **area** it measures, and the **metric** (soil moisture, pH, air temp, …).
  An *area* mapping fans out to every container currently in that area. Map as
  many sensors as you like; one sensor can map to several targets.
- **Remove sensor mappings** — prune mappings.

Readings appear on the container/plant **charts** in VerdiGrow. The integration
never renders dashboards and never touches hardware — it only reads mapped HA
states and pushes them.

## Roadmap (later versions)

- VerdiGrow objects as **native HA entities/cards** (device per container/plant,
  area assignment, latest photo) for HA dashboards.
- The VerdiGrow **panel** embedded in HA for daily interaction.

## License

[AGPL-3.0](LICENSE) © 2026 Jeff Hope
