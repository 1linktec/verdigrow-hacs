// VerdiGrow sidebar panel — the sensor-mapping tree/filter UI.
// Ships inside the HACS integration; runs in Home Assistant. Reads HA
// entities/areas natively (from `hass`) and VerdiGrow's catalog via the
// integration's local endpoints, and stores the map in HA. VerdiGrow only
// stores readings — it never sees this UI.

const SENSOR_DOMAINS = ["sensor", "binary_sensor", "number"];

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

class VerdiGrowPanel extends HTMLElement {
  constructor() {
    super();
    this._loaded = false;
    this._filterArea = "";
    this._search = "";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._init();
    }
  }

  async _init() {
    this.innerHTML = `<div style="padding:24px">Loading VerdiGrow…</div>`;
    try {
      const [catalog, maps] = await Promise.all([
        this._hass.callApi("GET", "verdigrow/catalog"),
        this._hass.callApi("GET", "verdigrow/mappings"),
      ]);
      if (catalog.error) throw new Error(catalog.error);
      this._catalog = catalog;
      this._links = {}; // "target|id|metric" -> entity_id
      this._excludes = {}; // "areaId|metric" -> Set(container ids) manually excluded from ambient
      (maps.links || []).forEach((l) => {
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

  _buildHaIndex() {
    const h = this._hass;
    const ent = h.entities || {}, dev = h.devices || {}, areas = h.areas || {};
    this._haAreas = areas;
    const byArea = {}, all = [];
    Object.keys(h.states || {}).forEach((eid) => {
      if (!SENSOR_DOMAINS.includes(eid.split(".")[0])) return;
      const e = ent[eid] || {};
      let aid = e.area_id;
      if (!aid && e.device_id && dev[e.device_id]) aid = dev[e.device_id].area_id;
      aid = aid || "";
      const st = h.states[eid];
      const item = {
        entity_id: eid,
        name: (st.attributes && st.attributes.friendly_name) || eid,
        state: st.state,
        unit: (st.attributes && st.attributes.unit_of_measurement) || "",
        area_id: aid,
      };
      all.push(item);
      (byArea[aid] = byArea[aid] || []).push(item);
    });
    all.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    this._haAll = all;
    this._haByArea = byArea;
  }

  _entitiesFor(areaId) {
    let list = areaId ? (this._haByArea[areaId] || []) : this._haAll;
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
        <select class="vg-pick" data-target="${target}" data-id="${id}"
                data-metric="${esc(m.key)}" data-current="${esc(current)}"></select>
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
        <select class="vg-pick" data-target="area" data-id="${area.id}"
                data-metric="${esc(m.key)}" data-current="${esc(current)}"></select>
        ${exclUI}
      </div>`;
    }).join("");
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

    const containerNode = (ct) => `
      <details class="vg-node">
        <summary>🪣 ${esc(ct.label)} <span class="vg-dim">· ${esc(ct.type)}${
          plantByContainer[ct.id] ? " · 🌱 " + esc(plantByContainer[ct.id]) : ""}</span></summary>
        <div class="vg-body">${this._metricRows("container", ct.id)}</div>
      </details>`;

    const areaNodes = (c.areas || []).map((a) => `
      <details class="vg-node" open>
        <summary>📍 ${esc(a.name)} <span class="vg-dim">· ambient — applies to every container in this area</span></summary>
        <div class="vg-body">
          ${this._areaMetricRows(a, containersByArea[a.id] || [])}
          ${(containersByArea[a.id] || []).map(containerNode).join("")}
        </div>
      </details>`).join("");

    const unassignedNode = unassigned.length ? `
      <details class="vg-node">
        <summary>🪣 Containers with no area</summary>
        <div class="vg-body">${unassigned.map(containerNode).join("")}</div>
      </details>` : "";

    const areaOptions = Object.values(this._haAreas)
      .filter((a) => (this._haByArea[a.area_id] || []).length)
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
      .map((a) => `<option value="${esc(a.area_id)}">${esc(a.name)} (${this._haByArea[a.area_id].length})</option>`)
      .join("");

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
      </style>
      <div class="vg-wrap">
        <h1>VerdiGrow Link — Sensor Mapping</h1>
        <p class="vg-help">Filter by HA area to cut the sensor list, expand a container (or an
          area), and pick a sensor for each metric. A sensor on a <strong>container</strong>
          (bed, row, pot, bucket, tray) is <em>dedicated</em>. A sensor on an <strong>area</strong>
          is <em>ambient</em> — the area stores nothing; the reading is recorded on every container
          currently in that area. Stored in Home Assistant; readings are pushed to VerdiGrow.</p>
        <div class="vg-bar">
          <label>HA area</label>
          <select id="vg-filter"><option value="">All HA areas</option>${areaOptions}</select>
          <input id="vg-search" placeholder="filter sensors…">
          <button class="vg-btn secondary" id="vg-expand" type="button">Expand all</button>
          <button class="vg-btn secondary" id="vg-collapse" type="button">Collapse all</button>
          <span id="vg-status" class="vg-status"></span>
          <span style="flex:1"></span>
          <button class="vg-btn secondary" id="vg-pushnow" type="button">Push now</button>
          <button class="vg-btn" id="vg-save" type="button">Save mapping</button>
        </div>
        ${areaNodes}${unassignedNode}
      </div>`;

    this._filterEl = this.querySelector("#vg-filter");
    this._searchEl = this.querySelector("#vg-search");
    this._statusEl = this.querySelector("#vg-status");
    this._selects = Array.from(this.querySelectorAll(".vg-pick"));
    this._filterEl.value = this._filterArea;
    this._searchEl.value = this._search;

    this._selects.forEach((s) => s.addEventListener("change", () => { s.dataset.current = s.value; }));
    this._filterEl.addEventListener("change", () => { this._filterArea = this._filterEl.value; this._fillSelects(); });
    this._searchEl.addEventListener("input", () => { this._search = this._searchEl.value; this._fillSelects(); });
    this.querySelector("#vg-save").addEventListener("click", () => this._save());
    this.querySelector("#vg-pushnow").addEventListener("click", () => this._pushNow());
    this.querySelector("#vg-expand").addEventListener("click", () =>
      this.querySelectorAll("details.vg-node").forEach((d) => { d.open = true; }));
    this.querySelector("#vg-collapse").addEventListener("click", () =>
      this.querySelectorAll("details.vg-node").forEach((d) => { d.open = false; }));
    this._fillSelects();
  }

  _fillSelects() {
    const list = this._entitiesFor(this._filterArea);
    this._statusEl.textContent = `${list.length} sensor${list.length === 1 ? "" : "s"}`
      + (this._filterArea ? " in this HA area" : " (all areas)");
    this._selects.forEach((sel) => {
      const current = sel.dataset.current || "";
      sel.innerHTML = "";
      const none = new Option("— none —", "");
      sel.appendChild(none);
      let hasCurrent = !current;
      list.forEach((e) => {
        if (e.entity_id === current) hasCurrent = true;
        const label = `${e.name} · ${e.entity_id}` + (e.state != null ? ` = ${e.state}${e.unit}` : "");
        sel.appendChild(new Option(label, e.entity_id));
      });
      if (current && !hasCurrent) sel.appendChild(new Option(`${current} (outside filter)`, current));
      sel.value = current;
    });
  }

  _gather() {
    const links = [];
    this._selects.filter((s) => s.value).forEach((s) => {
      const link = {
        target: s.dataset.target, id: Number(s.dataset.id),
        metric: s.dataset.metric, entity_id: s.value,
      };
      if (s.dataset.target === "area") {
        // Manual excludes = containers unchecked and not auto-disabled.
        link.exclude = Array.from(this.querySelectorAll(
          `.vg-excl[data-area="${s.dataset.id}"][data-metric="${s.dataset.metric}"]`))
          .filter((cb) => !cb.disabled && !cb.checked)
          .map((cb) => Number(cb.dataset.container));
      }
      links.push(link);
    });
    return links;
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
