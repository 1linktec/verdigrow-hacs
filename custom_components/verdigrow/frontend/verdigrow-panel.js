// VerdiGrow sidebar panel — the sensor-mapping tree/filter UI.
// Ships inside the HACS integration; runs in Home Assistant. Reads HA
// entities/areas natively (from `hass`) and VerdiGrow's catalog via the
// integration's local endpoints, and stores the map in HA. VerdiGrow only
// stores readings — it never sees this UI.

const SENSOR_DOMAINS = ["sensor", "binary_sensor", "number"];

// Module-level cache — survives the panel element being recreated when you
// navigate away and back, so re-opening is instant. Cleared by "Refresh".
let PANEL_CACHE = null;

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

class VerdiGrowPanel extends HTMLElement {
  constructor() {
    super();
    this._loaded = false;
    this._filterArea = "";
    this._filterType = "";
    this._search = "";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._init();
    }
  }

  async _init(force) {
    if (!PANEL_CACHE || force) {
      this.innerHTML = `<div style="padding:24px">Loading VerdiGrow…</div>`;
    }
    try {
      if (!PANEL_CACHE || force) {
        const q = force ? "?fresh=1" : "";
        const [catalog, maps, areas] = await Promise.all([
          this._hass.callApi("GET", "verdigrow/catalog" + q),
          this._hass.callApi("GET", "verdigrow/mappings"),
          this._hass.callApi("GET", "verdigrow/areas" + q),
        ]);
        if (catalog.error) throw new Error(catalog.error);
        PANEL_CACHE = { catalog, maps, areas, at: new Date() };
      }
      const d = PANEL_CACHE;
      this._catalog = d.catalog;
      this._areas = d.areas || { ha_areas: [], vg_areas: [], area_map: {} };
      this._cacheAt = d.at;
      this._links = {}; // "target|id|metric" -> entity_id
      this._excludes = {}; // "areaId|metric" -> Set(container ids) manually excluded from ambient
      ((d.maps && d.maps.links) || []).forEach((l) => {
        this._links[`${l.target}|${l.id}|${l.metric}`] = l.entity_id;
        if (l.target === "area" && Array.isArray(l.exclude)) {
          this._excludes[`${l.id}|${l.metric}`] = new Set(l.exclude);
        }
      });
      this._buildHaIndex();
      this._render();
    } catch (e) {
      this.innerHTML = `<div style="padding:24px;color:var(--error-color,red)">
        Could not load VerdiGrow: ${esc(e.message || e)}.<br>
        Check the VerdiGrow connection in Settings → Devices & Services.</div>`;
    }
  }

  _refresh() { PANEL_CACHE = null; this._init(true); }

  _buildHaIndex() {
    const h = this._hass;
    const ent = h.entities || {}, dev = h.devices || {}, areas = h.areas || {};
    this._haAreas = areas;
    const byArea = {}, all = [], classes = new Set();
    Object.keys(h.states || {}).forEach((eid) => {
      const domain = eid.split(".")[0];
      if (!SENSOR_DOMAINS.includes(domain)) return;
      const e = ent[eid] || {};
      let aid = e.area_id;
      if (!aid && e.device_id && dev[e.device_id]) aid = dev[e.device_id].area_id;
      aid = aid || "";
      const st = h.states[eid];
      const attrs = (st && st.attributes) || {};
      const dc = attrs.device_class || "";
      if (dc) classes.add(dc);
      const item = {
        entity_id: eid,
        name: attrs.friendly_name || eid,
        state: st.state,
        unit: attrs.unit_of_measurement || "",
        area_id: aid,
        domain: domain,
        device_class: dc,
      };
      all.push(item);
      (byArea[aid] = byArea[aid] || []).push(item);
    });
    all.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    this._haAll = all;
    this._haByArea = byArea;
    this._deviceClasses = Array.from(classes).sort();
  }

  _entitiesFor(areaId) {
    let list = areaId ? (this._haByArea[areaId] || []) : this._haAll;
    const t = this._filterType || "";
    if (t.startsWith("dc:")) { const dc = t.slice(3); list = list.filter((e) => e.device_class === dc); }
    else if (t.startsWith("dom:")) { const d = t.slice(4); list = list.filter((e) => e.domain === d); }
    const term = this._search.toLowerCase();
    if (term) list = list.filter((e) =>
      (e.entity_id + " " + e.name).toLowerCase().includes(term));
    return list;
  }

  _metricRows(target, id) {
    return (this._catalog.metric_types || []).map((m) => {
      const current = this._links[`${target}|${id}|${m.key}`] || "";
      return `<div class="vg-row">
        <span class="vg-metric">${esc(m.name)} <em>(${esc(m.unit)})</em></span>
        <input class="vg-pick" list="vg-ent-list" placeholder="type to search a sensor…"
               data-target="${target}" data-id="${id}"
               data-metric="${esc(m.key)}" data-current="${esc(current)}" value="${esc(current)}">
      </div>`;
    }).join("");
  }

  // Ambient metric rows for an area: the sensor picker plus a per-container
  // include/exclude list. A container with its own dedicated sensor for the
  // metric is auto-excluded (disabled); others default to included but can be
  // unchecked to exclude them from this ambient sensor.
  _areaMetricRows(area, containers) {
    return (this._catalog.metric_types || []).map((m) => {
      const current = this._links[`area|${area.id}|${m.key}`] || "";
      const exSet = this._excludes[`${area.id}|${m.key}`] || new Set();
      const cbs = containers.map((ct) => {
        const hasDedicated = !!this._links[`container|${ct.id}|${m.key}`];
        const excluded = hasDedicated || exSet.has(ct.id);
        return `<label class="vg-cb">
          <input type="checkbox" class="vg-excl" data-area="${area.id}"
                 data-metric="${esc(m.key)}" data-container="${ct.id}"
                 ${excluded ? "" : "checked"} ${hasDedicated ? "disabled" : ""}>
          ${esc(ct.label)}${hasDedicated ? ` <span class="vg-dim">(has own ${esc(m.name)} sensor)</span>` : ""}
        </label>`;
      }).join("");
      const exclUI = containers.length
        ? `<details class="vg-excl-wrap"><summary class="vg-dim">applies to ${containers.length} container(s) — choose which</summary>
             <div class="vg-cbs">${cbs}</div></details>`
        : `<span class="vg-dim">no containers in this area yet</span>`;
      return `<div class="vg-row vg-arow">
        <span class="vg-metric">${esc(m.name)} <em>(${esc(m.unit)})</em></span>
        <input class="vg-pick" list="vg-ent-list" placeholder="type to search a sensor…"
               data-target="area" data-id="${area.id}"
               data-metric="${esc(m.key)}" data-current="${esc(current)}" value="${esc(current)}">
        ${exclUI}
      </div>`;
    }).join("");
  }

  _gardensHtml() {
    const cards = this._cards || [];
    if (!cards.length) return "";
    const card = (c) => {
      const occ = (c.occupancy || []).map((o) => `<div class="vg-chartrow"><b>${esc(o.label)}</b> ${
        o.plants.length
          ? o.plants.map((p) => `<span class="vg-chip">${esc(p.variety)}${p.count > 1 ? " ×" + p.count : ""}</span>`).join("")
          : '<span class="vg-dim">empty</span>'}</div>`).join("");
      return `<div class="vg-card">
        ${c.image_url ? `<img class="vg-card-img" src="${esc(c.image_url)}" loading="lazy">` : ""}
        <div class="vg-card-title">${esc(c.label)}</div>
        <div class="vg-dim">${esc(c.type)}${c.area ? " · " + esc(c.area) : ""} · ${c.plant_count} plant(s)</div>
        <div class="vg-chart">${occ}</div>
        <button class="vg-btn secondary vg-card-open" data-card="${c.id}" type="button">View plants &amp; metrics</button>
      </div>`;
    };
    return `<details class="vg-node" open>
      <summary>🌿 Gardens — ${cards.length} container(s)</summary>
      <div class="vg-body"><div class="vg-cards">${cards.map(card).join("")}</div></div>
    </details>`;
  }

  async _openCard(id) {
    let d;
    try { d = await this._hass.callApi("GET", "verdigrow/cards?id=" + id); }
    catch (e) { alert("Error loading card: " + (e.message || e)); return; }
    const metrics = (d.metrics || []).map((m) =>
      `<span class="vg-chip">${esc(m.name)}: ${m.value}${esc(m.unit)}</span>`).join("")
      || '<span class="vg-dim">no readings yet</span>';
    const plants = (d.plants || []).map((p) => `<div class="vg-plant">
        ${p.photo_url ? `<img class="vg-plant-img" src="${esc(p.photo_url)}" loading="lazy">`
                      : `<div class="vg-plant-img vg-noimg">🌱</div>`}
        <div style="flex:1"><div class="vg-card-title">${esc(p.label)}</div>
          <div class="vg-dim">${esc(p.status)} · ${esc(p.where)}</div>
          ${p.note ? `<div class="vg-note">${esc(p.note)}</div>` : ""}
        </div></div>`).join("") || '<span class="vg-dim">No plants in this container.</span>';
    const ov = document.createElement("div");
    ov.className = "vg-overlay";
    ov.innerHTML = `<div class="vg-modal">
        <div class="vg-modal-head"><b>${esc(d.label)}</b>
          <button class="vg-btn secondary" id="vg-close" type="button">Close</button></div>
        <div class="vg-dim">${esc(d.type)}${d.area ? " · " + esc(d.area) : ""}</div>
        <div class="vg-metrics" style="margin:8px 0">${metrics}</div>
        <h4 style="margin:8px 0 4px">Plants</h4>${plants}
      </div>`;
    ov.addEventListener("click", (e) => { if (e.target === ov || e.target.id === "vg-close") ov.remove(); });
    this.appendChild(ov);
  }

  _areaSyncHtml() {
    const a = this._areas || { ha_areas: [], vg_areas: [], area_map: {} };
    const vgNames = new Set(a.vg_areas.map((v) => (v.name || "").toLowerCase()));
    const haNames = new Set(a.ha_areas.map((h) => (h.name || "").toLowerCase()));
    const missing = a.ha_areas.filter((h) => !vgNames.has((h.name || "").toLowerCase()));
    const vgOnly = a.vg_areas.filter((v) => !haNames.has((v.name || "").toLowerCase()));
    const matched = a.vg_areas.length - vgOnly.length;
    // HA → VerdiGrow: pick which to import (all checked by default).
    const importRows = missing.map((m) =>
      `<label class="vg-cb"><input type="checkbox" class="vg-imp" value="${esc(m.name)}" checked> ${esc(m.name)}</label>`).join("");
    // VerdiGrow-owned areas not in HA: create in HA, map to an existing one, or leave out.
    const vgRows = vgOnly.map((v) => `
      <div class="vg-row"><span class="vg-metric">${esc(v.name)}</span>
        <select class="vg-areamap" data-vg="${v.id}" data-name="${esc(v.name)}">
          <option value="">— leave out of HA —</option>
          <option value="__create__">➕ Create “${esc(v.name)}” in HA</option>
          ${a.ha_areas.map((h) => `<option value="${esc(h.area_id)}" ${a.area_map[v.id] === h.area_id ? "selected" : ""}>Map to: ${esc(h.name)}</option>`).join("")}
        </select></div>`).join("");
    return `
      <details class="vg-node" ${missing.length || vgOnly.length ? "open" : ""}>
        <summary>🔗 Area sync — ${matched} matched · ${missing.length} to import · ${vgOnly.length} to place</summary>
        <div class="vg-body">
          ${missing.length
            ? `<p class="vg-dim">In HA, not in VerdiGrow — choose which to import:</p>
               <div class="vg-cbs">${importRows}</div>
               <button class="vg-btn" id="vg-import-areas" type="button" style="margin-top:6px">Import selected into VerdiGrow</button>`
            : `<p class="vg-dim">Every HA area is in VerdiGrow ✓</p>`}
          ${vgOnly.length
            ? `<p class="vg-dim" style="margin-top:14px">In VerdiGrow, not in HA — create in HA, map to an existing HA area, or leave out:</p>
               ${vgRows}
               <button class="vg-btn secondary" id="vg-save-areamap" type="button" style="margin-top:6px">Save</button>`
            : ""}
          ${this._areaManageHtml(a)}
          <div><span id="vg-area-status" class="vg-status"></span></div>
        </div>
      </details>`;
  }

  // Walk back a sync: list every VerdiGrow area with a Remove button. Removing
  // un-imports it from VerdiGrow (and drops any VG→HA mapping); it never touches
  // the HA area. Blocked while the area still holds containers.
  _areaManageHtml(a) {
    if (!a.vg_areas.length) return "";
    const byArea = this._containersByArea || {};
    const haById = {};
    (a.ha_areas || []).forEach((h) => { haById[h.area_id] = h.name; });
    const rows = a.vg_areas.slice()
      .sort((x, y) => (x.name || "").localeCompare(y.name || ""))
      .map((v) => {
        const n = (byArea[v.id] || []).length;
        const mapped = a.area_map[v.id] ? haById[a.area_map[v.id]] : null;
        const tail = n
          ? `<span class="vg-dim">${n} container(s) — move them first</span>`
          : `<button class="vg-btn secondary vg-area-del" data-id="${v.id}" data-name="${esc(v.name)}" type="button">Remove</button>`;
        return `<div class="vg-row"><span class="vg-metric">${esc(v.name)}${mapped ? ` <span class="vg-dim">→ ${esc(mapped)}</span>` : ""}</span>${tail}</div>`;
      }).join("");
    return `
      <details class="vg-node" style="margin-top:14px">
        <summary>🗑 Remove VerdiGrow areas (walk back a sync)</summary>
        <div class="vg-body">
          <p class="vg-dim">Removing un-imports an area from VerdiGrow only — the HA area stays.</p>
          ${rows}
        </div>
      </details>`;
  }

  async _removeArea(id, name) {
    if (!confirm(`Remove “${name}” from VerdiGrow?\n\nThis deletes the VerdiGrow area (the HA area is untouched).`)) return;
    const st = this.querySelector("#vg-area-status");
    if (st) st.textContent = "Removing…";
    try {
      const res = await this._hass.callApi("POST", "verdigrow/areas",
        { action: "delete_vg", id: Number(id) });
      if (res && res.error) { if (st) st.textContent = "Can't remove: " + res.error; return; }
      this._areas = await this._hass.callApi("GET", "verdigrow/areas?fresh=1");
      if (PANEL_CACHE) PANEL_CACHE.areas = this._areas;
      if (st) st.textContent = `Removed “${name}”.`;
      this._render();
    } catch (e) { if (st) st.textContent = "Error: " + (e.message || e); }
  }

  async _importAreas() {
    const names = Array.from(this.querySelectorAll(".vg-imp:checked")).map((cb) => cb.value);
    const st = this.querySelector("#vg-area-status");
    if (!names.length) { if (st) st.textContent = "Tick at least one area to import."; return; }
    if (st) st.textContent = "Importing…";
    try {
      await this._hass.callApi("POST", "verdigrow/areas", { action: "import", names });
      this._areas = await this._hass.callApi("GET", "verdigrow/areas?fresh=1");
      if (PANEL_CACHE) PANEL_CACHE.areas = this._areas;
      this._render();
    } catch (e) { if (st) st.textContent = "Error: " + (e.message || e); }
  }

  async _saveAreaMap() {
    const map = {};
    const createNames = [];
    const createFor = {}; // vg id -> name
    this.querySelectorAll(".vg-areamap").forEach((s) => {
      if (s.value === "__create__") { createNames.push(s.dataset.name); createFor[s.dataset.vg] = s.dataset.name; }
      else if (s.value) { map[s.dataset.vg] = s.value; }
    });
    const st = this.querySelector("#vg-area-status"); if (st) st.textContent = "Saving…";
    try {
      if (createNames.length) {
        const res = await this._hass.callApi("POST", "verdigrow/areas",
          { action: "create_ha_areas", names: createNames });
        for (const vg in createFor) {
          const aid = (res.created || {})[createFor[vg]];
          if (aid) map[vg] = aid;
        }
        this._areas = await this._hass.callApi("GET", "verdigrow/areas?fresh=1");
      }
      await this._hass.callApi("POST", "verdigrow/areas", { action: "map", area_map: map });
      this._areas.area_map = map;
      if (PANEL_CACHE) PANEL_CACHE.areas = this._areas;
      if (st) st.textContent = "Saved.";
      this._render();
    } catch (e) { if (st) st.textContent = "Error: " + (e.message || e); }
  }

  _render() {
    const c = this._catalog;
    const containersByArea = {};
    const unassigned = [];
    (c.containers || []).forEach((ct) => {
      if (ct.area_id) (containersByArea[ct.area_id] = containersByArea[ct.area_id] || []).push(ct);
      else unassigned.push(ct);
    });
    const plantByContainer = {};
    (c.plants || []).forEach((p) => { if (p.container_id) plantByContainer[p.container_id] = p.label; });

    // Keep the data so node bodies can be built lazily (on expand) — building
    // all 137 nodes' rows up front is what made the panel slow.
    this._containersByArea = containersByArea;
    this._plantByContainer = plantByContainer;
    this._unassigned = unassigned;

    // Only show areas that actually hold containers — an ambient sensor only
    // fans out to containers, so empty areas (imported HA rooms) are just noise.
    const shownAreas = (c.areas || []).filter((a) => (containersByArea[a.id] || []).length);
    const hiddenAreas = (c.areas || []).length - shownAreas.length;
    const areaNodes = shownAreas.map((a) => `
      <details class="vg-node" data-node="a:${a.id}">
        <summary>📍 ${esc(a.name)} <span class="vg-dim">· ambient — applies to every container in this area</span></summary>
        <div class="vg-body" data-lazy="1"></div>
      </details>`).join("");
    const hiddenNote = hiddenAreas
      ? `<p class="vg-dim" style="font-size:12px">${hiddenAreas} area(s) with no containers hidden.</p>` : "";

    const unassignedNode = unassigned.length ? `
      <details class="vg-node" data-node="u">
        <summary>🪣 Containers with no area</summary>
        <div class="vg-body" data-lazy="1"></div>
      </details>` : "";

    const areaOptions = Object.values(this._haAreas)
      .filter((a) => (this._haByArea[a.area_id] || []).length)
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
      .map((a) => `<option value="${esc(a.area_id)}">${esc(a.name)} (${this._haByArea[a.area_id].length})</option>`)
      .join("");

    const typeOptions =
      `<optgroup label="Measurement">` +
      (this._deviceClasses || []).map((dc) => `<option value="dc:${esc(dc)}">${esc(dc)}</option>`).join("") +
      `</optgroup><optgroup label="Domain">` +
      SENSOR_DOMAINS.map((d) => `<option value="dom:${d}">${d}</option>`).join("") +
      `</optgroup>`;

    this.innerHTML = `
      <style>
        .vg-wrap{padding:16px;max-width:900px;margin:0 auto;color:var(--primary-text-color)}
        .vg-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;position:sticky;top:0;
          background:var(--card-background-color,#fff);padding:12px 0;z-index:2;border-bottom:1px solid var(--divider-color,#e0e0e0)}
        .vg-bar select,.vg-bar input{padding:7px;border-radius:6px;border:1px solid var(--divider-color,#ccc);
          background:var(--card-background-color);color:var(--primary-text-color)}
        .vg-btn{padding:8px 14px;border:none;border-radius:6px;background:var(--primary-color,#4a7);
          color:var(--text-primary-color,#fff);cursor:pointer;font-weight:600}
        .vg-btn.secondary{background:var(--secondary-background-color,#eee);color:var(--primary-text-color)}
        .vg-node{border:1px solid var(--divider-color,#e0e0e0);border-radius:8px;padding:6px 10px;margin:6px 0}
        .vg-node summary{cursor:pointer}
        .vg-body{padding:6px 0 6px 14px}
        .vg-row{display:flex;gap:10px;align-items:center;margin:4px 0;flex-wrap:wrap}
        .vg-metric{min-width:190px}.vg-metric em{color:var(--secondary-text-color)}
        .vg-dim{color:var(--secondary-text-color);font-weight:400}
        .vg-pick{flex:1;min-width:240px;max-width:420px;padding:6px;border-radius:6px;
          border:1px solid var(--divider-color,#ccc);background:var(--card-background-color);color:var(--primary-text-color)}
        .vg-status{color:var(--secondary-text-color);font-size:13px}
        .vg-help{color:var(--secondary-text-color);margin:6px 0 14px}
        .vg-excl-wrap{margin-left:6px}
        .vg-excl-wrap summary{cursor:pointer;font-size:13px}
        .vg-cbs{display:flex;flex-direction:column;gap:2px;padding:6px 0 6px 12px}
        .vg-cb{font-size:13px;display:flex;gap:6px;align-items:center}
        .vg-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
        .vg-card{border:1px solid var(--divider-color,#e0e0e0);border-radius:10px;padding:10px;
          display:flex;flex-direction:column;gap:6px;background:var(--card-background-color)}
        .vg-card-img{width:100%;height:120px;object-fit:cover;border-radius:8px}
        .vg-card-title{font-weight:600}
        .vg-chart{display:flex;flex-direction:column;gap:3px;font-size:12px}
        .vg-chartrow b{color:var(--secondary-text-color);font-weight:600;margin-right:4px}
        .vg-chip{display:inline-block;background:var(--secondary-background-color,#eee);
          border-radius:10px;padding:1px 8px;margin:1px 2px;font-size:12px}
        .vg-metrics{display:flex;flex-wrap:wrap;gap:4px}
        .vg-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9998;
          display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:24px}
        .vg-modal{background:var(--card-background-color,#fff);color:var(--primary-text-color);
          border-radius:12px;padding:16px;max-width:640px;width:100%}
        .vg-modal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
        .vg-plant{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--divider-color,#eee)}
        .vg-plant-img{width:56px;height:56px;object-fit:cover;border-radius:8px;flex:0 0 auto}
        .vg-noimg{display:flex;align-items:center;justify-content:center;background:var(--secondary-background-color,#eee);font-size:24px}
        .vg-note{font-size:13px;color:var(--secondary-text-color);margin-top:2px;white-space:pre-wrap}
      </style>
      <div class="vg-wrap">
        <h1>VerdiGrow Link ${this._cacheAt ? `<span class="vg-dim" style="font-size:12px;font-weight:400">· loaded ${this._cacheAt.toLocaleTimeString()}</span>` : ""}</h1>
        <p class="vg-help">Set up the link between Home Assistant and VerdiGrow: sync areas and map
          HA sensors to VerdiGrow metrics. Your containers &amp; plants appear as cards on their
          HA <strong>area</strong> dashboards (native entities), not here.</p>
        ${this._areaSyncHtml()}
        <h2 style="margin:18px 0 4px">Sensor mapping</h2>
        <p class="vg-help">Filter by HA area to cut the sensor list, expand a container (or an
          area), and pick a sensor for each metric. A sensor on a <strong>container</strong>
          (bed, row, pot, bucket, tray) is <em>dedicated</em>. A sensor on an <strong>area</strong>
          is <em>ambient</em> — the area stores nothing; the reading is recorded on every container
          currently in that area. Stored in Home Assistant; readings are pushed to VerdiGrow.</p>
        <datalist id="vg-ent-list"></datalist>
        <div class="vg-bar">
          <label>Area</label>
          <select id="vg-filter"><option value="">All areas</option>${areaOptions}</select>
          <label>Type</label>
          <select id="vg-type"><option value="">All types</option>${typeOptions}</select>
          <input id="vg-search" placeholder="filter sensors…">
          <button class="vg-btn secondary" id="vg-expand" type="button">Expand all</button>
          <button class="vg-btn secondary" id="vg-collapse" type="button">Collapse all</button>
          <span id="vg-status" class="vg-status"></span>
          <span style="flex:1"></span>
          <button class="vg-btn secondary" id="vg-refresh" type="button" title="Reload from VerdiGrow">↻ Refresh</button>
          <button class="vg-btn secondary" id="vg-pushnow" type="button">Push now</button>
          <button class="vg-btn" id="vg-save" type="button">Save mapping</button>
        </div>
        ${areaNodes}${unassignedNode}${hiddenNote}
      </div>`;

    this._filterEl = this.querySelector("#vg-filter");
    this._typeEl = this.querySelector("#vg-type");
    this._searchEl = this.querySelector("#vg-search");
    this._statusEl = this.querySelector("#vg-status");
    this._datalist = this.querySelector("#vg-ent-list");
    this._selects = [];  // .vg-pick comboboxes, grows as node bodies are built
    this._filterEl.value = this._filterArea;
    this._typeEl.value = this._filterType;
    this._searchEl.value = this._search;
    this._fillDatalist();

    this._filterEl.addEventListener("change", () => { this._filterArea = this._filterEl.value; this._refill(); });
    this._typeEl.addEventListener("change", () => { this._filterType = this._typeEl.value; this._refill(); });
    this._searchEl.addEventListener("input", () => { this._search = this._searchEl.value; this._refill(); });
    this.querySelector("#vg-save").addEventListener("click", () => this._save());
    this.querySelector("#vg-pushnow").addEventListener("click", () => this._pushNow());
    this.querySelector("#vg-expand").addEventListener("click", () => {
      this.querySelectorAll("details.vg-node").forEach((d) => { d.open = true; this._buildNodeBody(d); });
      this._updateStatus();
    });
    this.querySelector("#vg-collapse").addEventListener("click", () =>
      this.querySelectorAll("details.vg-node").forEach((d) => { d.open = false; }));
    // Lazy: build a node's rows only when it opens — building all nodes' rows up
    // front froze the page. Pickers are comboboxes sharing one <datalist>, so
    // there's no per-row option-fill to do.
    this.addEventListener("toggle", (e) => {
      if (e.target && e.target.open) this._buildNodeBody(e.target);
    }, true);
    const rf = this.querySelector("#vg-refresh");
    if (rf) rf.addEventListener("click", () => this._refresh());
    const imp = this.querySelector("#vg-import-areas");
    if (imp) imp.addEventListener("click", () => this._importAreas());
    const sm = this.querySelector("#vg-save-areamap");
    if (sm) sm.addEventListener("click", () => this._saveAreaMap());
    this.querySelectorAll(".vg-area-del").forEach((b) =>
      b.addEventListener("click", () => this._removeArea(b.dataset.id, b.dataset.name)));
    this._updateStatus();
  }

  _containerSummary(ct) {
    const plant = this._plantByContainer[ct.id];
    return `<details class="vg-node" data-node="c:${ct.id}">
      <summary>🪣 ${esc(ct.label)} <span class="vg-dim">· ${esc(ct.type)}${plant ? " · 🌱 " + esc(plant) : ""}</span></summary>
      <div class="vg-body" data-lazy="1"></div>
    </details>`;
  }

  _buildNodeBody(details) {
    const body = details.querySelector(":scope > .vg-body");
    if (!body || !body.dataset.lazy) return;
    const node = details.dataset.node || "";
    let html = "";
    if (node.startsWith("c:")) {
      html = this._metricRows("container", parseInt(node.slice(2), 10));
    } else if (node.startsWith("a:")) {
      const id = parseInt(node.slice(2), 10);
      const area = (this._catalog.areas || []).find((x) => x.id === id);
      const conts = this._containersByArea[id] || [];
      html = this._areaMetricRows(area, conts) + conts.map((ct) => this._containerSummary(ct)).join("");
    } else if (node === "u") {
      html = (this._unassigned || []).map((ct) => this._containerSummary(ct)).join("");
    }
    body.innerHTML = html;
    delete body.dataset.lazy;
    // Track pickers; remember the chosen value (so _gather can read it).
    Array.from(body.querySelectorAll(".vg-pick")).forEach((s) => {
      if (!this._selects.includes(s)) {
        s.addEventListener("change", () => { s.dataset.current = s.value; });
        this._selects.push(s);
      }
    });
  }

  _updateStatus() {
    if (!this._statusEl) return;
    const n = this._entitiesFor(this._filterArea).length;
    const bits = [];
    if (this._filterArea) bits.push("this area");
    if (this._filterType) bits.push(this._filterType.replace(/^dc:|^dom:/, ""));
    this._statusEl.textContent = `${n} sensor${n === 1 ? "" : "s"}`
      + (bits.length ? " · " + bits.join(" · ") : " (all)") + " · type in a row to pick";
  }

  // One shared <datalist> that every combobox picker reads from — filtered by
  // area + type + search. Type-ahead in each row filters this list natively, so
  // there's never a 1600-option scroll.
  _fillDatalist() {
    if (!this._datalist) return;
    const list = this._entitiesFor(this._filterArea);
    this._datalist.innerHTML = list.map((e) => {
      const val = e.state != null && e.state !== "" ? ` = ${e.state}${e.unit}` : "";
      return `<option value="${esc(e.entity_id)}">${esc(e.name)}${esc(val)}</option>`;
    }).join("");
    this._updateStatus();
  }

  _refill() {
    // Area / type / search changed — rebuild the shared datalist.
    this._fillDatalist();
  }

  _gather() {
    // Start from the loaded mappings so nodes that were never expanded (their
    // selects don't exist yet) aren't dropped, then apply edits from any built
    // selects.
    const byKey = {};
    for (const k in this._links) {
      const [target, id, metric] = k.split("|");
      const link = { target, id: Number(id), metric, entity_id: this._links[k] };
      if (target === "area" && this._excludes[id + "|" + metric]) {
        link.exclude = Array.from(this._excludes[id + "|" + metric]);
      }
      byKey[k] = link;
    }
    const valid = new Set(this._haAll.map((e) => e.entity_id));
    this._selects.forEach((s) => {
      const key = `${s.dataset.target}|${s.dataset.id}|${s.dataset.metric}`;
      const v = (s.value || "").trim();
      if (!v) { delete byKey[key]; return; }
      if (!valid.has(v)) return;  // ignore free-typed text that isn't an entity
      const link = { target: s.dataset.target, id: Number(s.dataset.id),
                     metric: s.dataset.metric, entity_id: v };
      if (s.dataset.target === "area") {
        link.exclude = Array.from(this.querySelectorAll(
          `.vg-excl[data-area="${s.dataset.id}"][data-metric="${s.dataset.metric}"]`))
          .filter((cb) => !cb.disabled && !cb.checked)
          .map((cb) => Number(cb.dataset.container));
      }
      byKey[key] = link;
    });
    return Object.values(byKey);
  }

  async _save() {
    this._statusEl.textContent = "Saving…";
    try {
      const d = await this._hass.callApi("POST", "verdigrow/mappings", { links: this._gather() });
      this._statusEl.textContent = `Saved ${d.count} mapping(s) and pushed.`;
    } catch (e) {
      this._statusEl.textContent = "Error: " + (e.message || e);
    }
  }

  async _pushNow() {
    this._statusEl.textContent = "Pushing…";
    try {
      const d = await this._hass.callApi("POST", "verdigrow/push");
      this._statusEl.textContent = `Pushed ${d.pushed} reading(s).`;
    } catch (e) {
      this._statusEl.textContent = "Error: " + (e.message || e);
    }
  }
}

customElements.define("verdigrow-panel", VerdiGrowPanel);
