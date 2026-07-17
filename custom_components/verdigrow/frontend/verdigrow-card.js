// VerdiGrow container card — a rich Lovelace card for one container:
// its photo, the planting chart (what's in each row, to scale), the plants in it
// (with their photos + latest note), and the latest metrics.
// Add to a dashboard: type: custom:verdigrow-container-card, entity: a VerdiGrow
// "<container> Plants" sensor (or container: <id>).

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

class VerdiGrowContainerCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity && !config.container) {
      throw new Error("Set 'entity' (a VerdiGrow sensor) or 'container' (id).");
    }
    this._config = config;
    this._loaded = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  _containerId() {
    if (this._config.container) return this._config.container;
    const ent = (this._hass.entities || {})[this._config.entity];
    const dev = ent && ent.device_id ? (this._hass.devices || {})[ent.device_id] : null;
    if (dev && dev.identifiers) {
      for (const pair of dev.identifiers) {
        if (pair[0] === "verdigrow" && String(pair[1]).startsWith("container_")) {
          return parseInt(String(pair[1]).split("_")[1], 10);
        }
      }
    }
    return null;
  }

  async _load() {
    const id = this._containerId();
    if (!id) { this._shell("Point this card at a VerdiGrow container entity."); return; }
    try {
      this._card = await this._hass.callApi("GET", "verdigrow/cards?id=" + id);
      this._render();
    } catch (e) {
      this._shell("Could not load: " + (e.message || e));
    }
  }

  _shell(msg) {
    this.innerHTML = `<ha-card><div style="padding:16px">${esc(msg)}</div></ha-card>`;
  }

  _render() {
    const c = this._card;
    const bars = (c.occupancy || []).map((o) => {
      const total = o.total_cm, used = o.used_cm || 0;
      const pct = total ? Math.min(100, Math.round((used / total) * 100)) : (o.plants.length ? 100 : 0);
      const chips = o.plants.length
        ? o.plants.map((p) => `<span class="vg-chip">${esc(p.variety)}${p.count > 1 ? " ×" + p.count : ""}</span>`).join("")
        : '<span class="vg-dim">empty</span>';
      return `<div class="vg-row">
          <div class="vg-rowhead"><b>${esc(o.label)}</b>${total ? ` <span class="vg-dim">${pct}%</span>` : ""}</div>
          <div class="vg-bar"><div class="vg-fill" style="width:${pct}%"></div></div>
          <div class="vg-chips">${chips}</div>
        </div>`;
    }).join("");

    const metrics = (c.metrics || []).map((m) =>
      `<span class="vg-chip">${esc(m.name)}: ${m.value}${esc(m.unit || "")}</span>`).join("");

    const plants = (c.plants || []).map((p) => `<div class="vg-plant">
        ${p.photo_url ? `<img class="vg-pimg" src="${esc(p.photo_url)}" loading="lazy">`
                      : `<div class="vg-pimg vg-noimg">🌱</div>`}
        <div style="flex:1">
          <div><b>${esc(p.label)}</b></div>
          <div class="vg-dim">${esc(p.status)} · ${esc(p.where)}</div>
          ${p.note ? `<div class="vg-note">${esc(p.note)}</div>` : ""}
        </div></div>`).join("") || '<div class="vg-dim">No plants.</div>';

    this.innerHTML = `
      <ha-card header="${esc(c.label)}">
        <style>
          .vg-body{padding:0 16px 16px}
          .vg-sub{color:var(--secondary-text-color);margin-top:-6px;margin-bottom:8px}
          .vg-hero{width:100%;max-height:200px;object-fit:cover;border-radius:8px;margin-bottom:10px}
          .vg-row{margin:6px 0}
          .vg-rowhead{font-size:13px;display:flex;gap:6px;justify-content:space-between}
          .vg-bar{height:8px;border-radius:5px;background:var(--divider-color,#e0e0e0);overflow:hidden;margin:3px 0}
          .vg-fill{height:100%;background:var(--primary-color,#4a7)}
          .vg-chips{display:flex;flex-wrap:wrap;gap:3px}
          .vg-chip{display:inline-block;background:var(--secondary-background-color,#eee);border-radius:10px;padding:1px 8px;font-size:12px}
          .vg-dim{color:var(--secondary-text-color)}
          .vg-metrics{display:flex;flex-wrap:wrap;gap:4px;margin:10px 0}
          .vg-plant{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--divider-color,#eee)}
          .vg-pimg{width:52px;height:52px;object-fit:cover;border-radius:8px;flex:0 0 auto}
          .vg-noimg{display:flex;align-items:center;justify-content:center;background:var(--secondary-background-color,#eee);font-size:22px}
          .vg-note{font-size:13px;color:var(--secondary-text-color);white-space:pre-wrap;margin-top:2px}
        </style>
        <div class="vg-body">
          <div class="vg-sub">${esc(c.type)}${c.area ? " · " + esc(c.area) : ""} · ${c.plant_count} plant(s)</div>
          ${c.image_url ? `<img class="vg-hero" src="${esc(c.image_url)}" loading="lazy">` : ""}
          ${bars}
          ${metrics ? `<div class="vg-metrics">${metrics}</div>` : ""}
          <div>${plants}</div>
        </div>
      </ha-card>`;
  }

  getCardSize() {
    return 4 + ((this._card && this._card.plants ? this._card.plants.length : 0));
  }

  static getStubConfig(hass) {
    const entities = hass && hass.entities ? hass.entities : {};
    const ent = Object.keys(entities).find(
      (e) => e.endsWith("_plants") && entities[e].platform === "verdigrow");
    return { entity: ent || "" };
  }
}

customElements.define("verdigrow-container-card", VerdiGrowContainerCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "verdigrow-container-card",
  name: "VerdiGrow Container",
  description: "A VerdiGrow container: photo, planting chart, plants and metrics.",
});
