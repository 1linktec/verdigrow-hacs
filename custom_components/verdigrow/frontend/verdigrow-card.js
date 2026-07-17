// VerdiGrow card — a rich Lovelace card for one container OR one plant:
// photo, planting chart (containers), plants with photos + notes, and metrics.
// Configure visually (pick an area, then a container or plant) or in YAML:
//   type: custom:verdigrow-container-card
//   target: "container:12"   # or "plant:34"

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const CARD_STYLE = `
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
  .vg-note{font-size:13px;color:var(--secondary-text-color);white-space:pre-wrap;margin-top:2px}`;

class VerdiGrowCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._kind = null;
    this._id = null;
    if (config.target) {
      const [k, i] = String(config.target).split(":");
      this._kind = k; this._id = i;
    } else if (config.container) {
      this._kind = "container"; this._id = config.container;
    } else if (config.plant) {
      this._kind = "plant"; this._id = config.plant;
    } else if (config.entity) {
      this._kind = "entity"; this._entity = config.entity;
    }
    this._loaded = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) { this._loaded = true; this._load(); }
  }

  _resolveEntity() {
    const ent = (this._hass.entities || {})[this._entity];
    const dev = ent && ent.device_id ? (this._hass.devices || {})[ent.device_id] : null;
    if (dev && dev.identifiers) {
      for (const pair of dev.identifiers) {
        if (pair[0] === "verdigrow" && String(pair[1]).startsWith("container_")) {
          return ["container", parseInt(String(pair[1]).split("_")[1], 10)];
        }
      }
    }
    return null;
  }

  async _load() {
    let kind = this._kind, id = this._id;
    if (kind === "entity") {
      const r = this._resolveEntity();
      if (r) { kind = r[0]; id = r[1]; }
    }
    if (!kind || !id) {
      this._shell("Configure this card — pick an area, then a container or plant.");
      return;
    }
    const q = kind === "plant" ? "plant=" + id : "id=" + id;
    try {
      this._card = await this._hass.callApi("GET", "verdigrow/cards?" + q);
      this._resolvedKind = kind;
      this._render();
    } catch (e) {
      this._shell("Could not load: " + (e.message || e));
    }
  }

  _shell(msg) {
    this.innerHTML = `<ha-card><div style="padding:16px">${esc(msg)}</div></ha-card>`;
  }

  _render() {
    if (this._resolvedKind === "plant") this._renderPlant();
    else this._renderContainer();
  }

  _metricsHtml(c) {
    return (c.metrics || []).map((m) =>
      `<span class="vg-chip">${esc(m.name)}: ${m.value}${esc(m.unit || "")}</span>`).join("");
  }

  _renderContainer() {
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
          <div class="vg-chips">${chips}</div></div>`;
    }).join("");
    const metrics = this._metricsHtml(c);
    const plants = (c.plants || []).map((p) => `<div class="vg-plant">
        ${p.photo_url ? `<img class="vg-pimg" src="${esc(p.photo_url)}" loading="lazy">` : `<div class="vg-pimg vg-noimg">🌱</div>`}
        <div style="flex:1"><div><b>${esc(p.label)}</b></div>
          <div class="vg-dim">${esc(p.status)} · ${esc(p.where)}</div>
          ${p.note ? `<div class="vg-note">${esc(p.note)}</div>` : ""}</div></div>`).join("")
      || '<div class="vg-dim">No plants.</div>';
    this.innerHTML = `<ha-card header="${esc(c.label)}"><style>${CARD_STYLE}</style>
      <div class="vg-body">
        <div class="vg-sub">${esc(c.type)}${c.area ? " · " + esc(c.area) : ""} · ${c.plant_count} plant(s)</div>
        ${c.image_url ? `<img class="vg-hero" src="${esc(c.image_url)}" loading="lazy">` : ""}
        ${bars}
        ${metrics ? `<div class="vg-metrics">${metrics}</div>` : ""}
        <div>${plants}</div>
      </div></ha-card>`;
  }

  _renderPlant() {
    const c = this._card;
    const seed = c.seed
      ? `<div class="vg-dim">Seed: ${esc(c.seed.variety)}${c.seed.supplier ? " · " + esc(c.seed.supplier) : ""}${c.seed.spacing_cm ? " · " + c.seed.spacing_cm + "cm" : ""}${c.seed.code ? " · " + esc(c.seed.code) : ""}</div>` : "";
    this.innerHTML = `<ha-card header="${esc(c.label)}"><style>${CARD_STYLE}</style>
      <div class="vg-body">
        <div class="vg-sub">${esc(c.crop)} ${esc(c.variety)} · ${esc(c.status)}${c.days_to_maturity ? " · " + c.days_to_maturity + "d" : ""} · in ${esc(c.where)}</div>
        ${c.image_url ? `<img class="vg-hero" src="${esc(c.image_url)}" loading="lazy">` : ""}
        ${c.note ? `<div class="vg-note">${esc(c.note)}</div>` : ""}
        ${seed}
        ${c.metrics && c.metrics.length ? `<div class="vg-metrics">${this._metricsHtml(c)}</div>` : ""}
      </div></ha-card>`;
  }

  getCardSize() {
    const n = this._card && this._card.plants ? this._card.plants.length : 0;
    return 3 + n;
  }

  static getStubConfig() { return {}; }        // no auto-pick — user chooses
  static getConfigElement() { return document.createElement("verdigrow-card-editor"); }
}

customElements.define("verdigrow-container-card", VerdiGrowCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "verdigrow-container-card",
  name: "VerdiGrow",
  description: "A VerdiGrow container or plant: photo, planting chart, plants, metrics.",
  preview: false,
});


// ── Visual editor: pick an area, then a container or plant ──────────────────
class VerdiGrowCardEditor extends HTMLElement {
  setConfig(config) { this._config = config || {}; this._render(); }

  set hass(hass) {
    this._hass = hass;
    if (!this._catalog) this._loadCatalog();
  }

  async _loadCatalog() {
    try {
      this._catalog = await this._hass.callApi("GET", "verdigrow/catalog");
      this._render();
    } catch (e) {
      this.innerHTML = `<div style="padding:8px;color:var(--error-color,red)">Could not load VerdiGrow: ${esc(e.message || e)}</div>`;
    }
  }

  _currentTarget() {
    const c = this._config || {};
    if (c.target) return String(c.target);
    if (c.container) return "container:" + c.container;
    if (c.plant) return "plant:" + c.plant;
    return "";
  }

  _emit(target) {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: { type: "custom:verdigrow-container-card", target } },
      bubbles: true, composed: true,
    }));
  }

  _render() {
    if (!this._catalog) { this.innerHTML = `<div style="padding:8px">Loading…</div>`; return; }
    const cat = this._catalog;
    const areas = cat.areas || [];
    const cur = this._currentTarget();
    // Which area is selected? Derive from the current target's object, else this._area, else first.
    let curId = null, curKind = null;
    if (cur) { const [k, i] = cur.split(":"); curKind = k; curId = parseInt(i, 10); }
    let areaId = this._area;
    if (areaId == null && curId != null) {
      const obj = curKind === "plant"
        ? (cat.plants || []).find((p) => p.id === curId)
        : (cat.containers || []).find((c) => c.id === curId);
      if (obj) areaId = obj.area_id;
    }
    if (areaId == null) areaId = areas.length ? areas[0].id : "";
    this._area = areaId;

    const areaOpts = [`<option value="">— all / unassigned —</option>`].concat(
      areas.map((a) => `<option value="${a.id}" ${String(a.id) === String(areaId) ? "selected" : ""}>${esc(a.name)}</option>`)).join("");

    const inArea = (o) => String(o.area_id || "") === String(areaId || "");
    const conts = (cat.containers || []).filter(inArea);
    const plants = (cat.plants || []).filter(inArea);
    const tgtOpts = [`<option value="">— pick a container or plant —</option>`,
      conts.length ? `<optgroup label="Containers">` +
        conts.map((c) => `<option value="container:${c.id}" ${cur === "container:" + c.id ? "selected" : ""}>${esc(c.label)} (${esc(c.type)})</option>`).join("") + `</optgroup>` : "",
      plants.length ? `<optgroup label="Plants">` +
        plants.map((p) => `<option value="plant:${p.id}" ${cur === "plant:" + p.id ? "selected" : ""}>${esc(p.label)}</option>`).join("") + `</optgroup>` : "",
    ].join("");

    this.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;padding:8px 0">
        <label>Area
          <select id="vg-ed-area" style="width:100%;padding:8px;margin-top:4px">${areaOpts}</select>
        </label>
        <label>Show
          <select id="vg-ed-target" style="width:100%;padding:8px;margin-top:4px">${tgtOpts}</select>
        </label>
      </div>`;
    this.querySelector("#vg-ed-area").addEventListener("change", (e) => {
      this._area = e.target.value === "" ? "" : parseInt(e.target.value, 10);
      this._render();
    });
    this.querySelector("#vg-ed-target").addEventListener("change", (e) => {
      if (e.target.value) this._emit(e.target.value);
    });
  }
}
customElements.define("verdigrow-card-editor", VerdiGrowCardEditor);
