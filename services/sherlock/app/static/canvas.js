const NODE_COLORS = {
  Application: "#4f46e5",
  Endpoint:    "#10b981",
  Topic:       "#f59e0b",
  DBSchema:    "#8b5cf6",
  DBTable:     "#a855f7",
  FileFeed:    "#14b8a6",
  Library:     "#64748b",
};

const DEFAULT_HIDDEN = new Set(["DBSchema", "Library"]);
const DEFAULT_KINDS_HIDDEN = new Set(["LIB"]);

let cy;
let contractGraph = null;
let appGraph = null;
let appsList = [];
let mode = "app"; // "app" | "contract"
let selectedAppName = null;
let showArchived = false;

// --- Styling ----------------------------------------------------------------

const NODE_STYLE_BASE = [
  {
    selector: "node",
    style: {
      "background-color": (n) => NODE_COLORS[n.data("label")] || "#94a3b8",
      "label": "data(name)",
      "color": "#1A1A1A",
      "font-size": 10,
      "font-weight": 400,
      // labels sit BELOW the node so they can be plain black on the light canvas
      "text-valign": "bottom",
      "text-halign": "center",
      "text-margin-y": 5,
      "text-wrap": "wrap",
      "text-max-width": 150,
      // Application: 50 → 30 (−40%).  Other node types: 32 → 26 (−20%).
      "width": (n) => (n.data("label") === "Application" ? 30 : 26),
      "height": (n) => (n.data("label") === "Application" ? 30 : 26),
      "border-width": 0,
      "overlay-opacity": 0,
      // no text outline/stroke — plain black on light background
    },
  },
  { selector: 'node[label="Application"]', style: { "font-size": 11, "font-weight": 500 } },
  { selector: 'node[label="Endpoint"]',    style: { "shape": "rectangle" } },
  { selector: 'node[label="Topic"]',       style: { "shape": "diamond" } },
  { selector: 'node[label="DBTable"]',     style: { "shape": "hexagon" } },
  { selector: 'node[label="FileFeed"]',    style: { "shape": "cut-rectangle" } },

  // highlight / dim / impact states (shared)
  { selector: ".dim",     style: { "opacity": 0.25 } },
  { selector: ".highlight", style: { "border-width": 3, "border-color": "#EC0016" } },
  { selector: ".impact",  style: { "background-color": "#F97316", "border-width": 2, "border-color": "#EA580C" } },
  { selector: ".impact-edge", style: { "line-color": "#F97316", "target-arrow-color": "#F97316", "width": 2.5 } },

  // Platform-coloured ring on Application nodes — visible cross-boundary marker
  { selector: 'node[label="Application"][platform = "azure"]',
    style: { "border-width": 3, "border-color": "#0078D4" /* Azure blue */ } },
  { selector: 'node[label="Application"][platform = "on-prem"]',
    style: { "border-width": 3, "border-color": "#6B7280" /* slate */ } },
  { selector: 'node[label="Application"][platform = "library"]',
    style: { "border-width": 2, "border-color": "#CBD5E1", "border-style": "dotted" } },

  // Archived apps — faded, dashed border (overrides platform ring)
  {
    selector: 'node[label="Application"][?archived]',
    style: {
      "opacity": 0.45,
      "border-width": 2,
      "border-color": "#888",
      "border-style": "dashed",
    },
  },
];

const EDGE_STYLE_CONTRACT = [
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      "width": 1.2,
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.9,
      "line-color": "#94A3B8",
      "target-arrow-color": "#94A3B8",
      "font-size": 8,
      "font-weight": 400,
      "color": "#1A1A1A",
      "text-background-color": "#FFFFFF",
      "text-background-opacity": 0.85,
      "text-background-padding": 2,
    },
  },
  // EXPOSES is the OWNER edge — make it visually dominant, no arrow
  { selector: 'edge[kind="EXPOSES"]', style: {
      "width": 3.5, "line-color": "#6366f1", "target-arrow-color": "#6366f1",
      "target-arrow-shape": "none", "line-style": "solid", "label": "owns",
    } },
  { selector: 'edge[kind="CALLS"]',          style: { "line-color": "#10b981", "target-arrow-color": "#10b981", "label": "calls" } },
  { selector: 'edge[kind="PUBLISHES"]',      style: { "line-color": "#f59e0b", "target-arrow-color": "#f59e0b", "label": "pub" } },
  { selector: 'edge[kind="CONSUMES"]',       style: { "line-color": "#f59e0b", "target-arrow-color": "#f59e0b", "line-style": "dashed", "label": "sub" } },
  { selector: 'edge[kind="READS_TABLE"]',    style: { "line-color": "#a855f7", "target-arrow-color": "#a855f7", "line-style": "dashed", "label": "reads" } },
  { selector: 'edge[kind="WRITES_TABLE"]',   style: { "line-color": "#a855f7", "target-arrow-color": "#a855f7", "label": "writes" } },
  { selector: 'edge[kind="OWNS_SCHEMA"]',    style: { "line-color": "#8b5cf6", "target-arrow-color": "#8b5cf6" } },
  { selector: 'edge[kind="DEPENDS_ON_LIB"]', style: { "line-color": "#64748b", "target-arrow-color": "#64748b" } },
  { selector: 'edge[kind="PUBLISHES_LIB"]',  style: { "line-color": "#64748b", "target-arrow-color": "#64748b" } },
  { selector: 'edge[kind="CONTAINS_TABLE"]', style: { "line-color": "#CBD5E1", "target-arrow-color": "#CBD5E1" } },
  { selector: 'edge[kind="READS_FILE"]',     style: { "line-color": "#14b8a6", "target-arrow-color": "#14b8a6", "line-style": "dashed", "label": "reads" } },
  { selector: 'edge[kind="WRITES_FILE"]',    style: { "line-color": "#14b8a6", "target-arrow-color": "#14b8a6", "label": "writes" } },
];

const EDGE_STYLE_APP = [
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      "width": 1.6,
      "target-arrow-shape": "triangle",
      "arrow-scale": 1,
      "line-color": "#94A3B8",
      "target-arrow-color": "#94A3B8",
      "font-size": 9,
      "font-weight": 400,
      "color": "#1A1A1A",
      "text-background-color": "#FFFFFF",
      "text-background-opacity": 0.9,
      "text-background-padding": 3,
      "label": "data(label)",
    },
  },
  { selector: 'edge[kind="REST"]',  style: { "line-color": "#10b981", "target-arrow-color": "#10b981" } },
  { selector: 'edge[kind="EVENT"]', style: { "line-color": "#f59e0b", "target-arrow-color": "#f59e0b", "line-style": "dashed" } },
  { selector: 'edge[kind="DB"]',    style: { "line-color": "#a855f7", "target-arrow-color": "#a855f7", "line-style": "dashed" } },
  { selector: 'edge[kind="FILE"]',  style: { "line-color": "#14b8a6", "target-arrow-color": "#14b8a6", "line-style": "dashed" } },
  { selector: 'edge[kind="LIB"]',   style: { "line-color": "#64748b", "target-arrow-color": "#64748b" } },
];

function styleForMode(m) {
  return [...NODE_STYLE_BASE, ...(m === "app" ? EDGE_STYLE_APP : EDGE_STYLE_CONTRACT)];
}

// A little more rank separation so below-node labels don't crowd the next rank
const LAYOUT = { name: "dagre", rankDir: "BT", nodeSep: 80, rankSep: 140, animate: false };

// --- Boot -------------------------------------------------------------------

async function fetchAll() {
  const q = `?include_archived=${showArchived ? "true" : "false"}`;
  const [g1, g2, a] = await Promise.all([
    fetch("/api/graph" + q).then((r) => r.json()),
    fetch("/api/app-graph" + q).then((r) => r.json()),
    fetch("/api/apps").then((r) => r.json()),  // always full list; sidebar styles archived
  ]);
  contractGraph = g1;
  appGraph = g2;
  appsList = a;
}

async function init() {
  await fetchAll();

  cy = cytoscape({
    container: document.getElementById("cy"),
    elements: [],
    style: styleForMode(mode),
    layout: LAYOUT,
    wheelSensitivity: 0.2,
  });

  cy.on("tap", "node", (evt) => selectNode(evt.target));
  cy.on("tap", (evt) => { if (evt.target === cy) deselect(); });

  // Node-type filters (contract view)
  for (const kind of Object.keys(NODE_COLORS)) {
    const el = document.getElementById(`toggle-${kind}`);
    if (!el) continue;
    el.checked = !DEFAULT_HIDDEN.has(kind);
    el.addEventListener("change", render);
  }
  // Edge-kind filters (app view)
  for (const kind of ["REST", "EVENT", "DB", "FILE", "LIB"]) {
    const el = document.getElementById(`toggle-kind-${kind}`);
    if (!el) continue;
    el.checked = !DEFAULT_KINDS_HIDDEN.has(kind);
    el.addEventListener("change", render);
  }

  document.getElementById("team-filter").addEventListener("change", render);
  document.getElementById("platform-filter").addEventListener("change", render);
  document.getElementById("mode-app").addEventListener("click", () => setMode("app"));
  document.getElementById("mode-contract").addEventListener("click", () => setMode("contract"));
  document.getElementById("impact-downstream").addEventListener("click", () => showImpact("downstream"));
  document.getElementById("impact-upstream").addEventListener("click", () => showImpact("upstream"));
  document.getElementById("clear-impact").addEventListener("click", clearImpact);
  document.getElementById("generate-docs").addEventListener("click", generateDocs);

  const archivedToggle = document.getElementById("toggle-archived");
  archivedToggle.checked = showArchived;
  archivedToggle.addEventListener("change", async () => {
    showArchived = archivedToggle.checked;
    await fetchAll();
    renderSidebar();
    render();
  });

  setupSidebarResize();
  renderSidebar();
  setMode("app");
}

// --- Resizable sidebar -------------------------------------------------------

function setupSidebarResize() {
  const STORAGE_KEY = "sherlock.sidebarWidth";
  const MIN = 180;
  const MAX = 480;
  const DEFAULT = 240;

  const root = document.documentElement;
  const resizer = document.getElementById("sidebar-resizer");
  if (!resizer) return;

  const saved = parseInt(localStorage.getItem(STORAGE_KEY), 10);
  if (Number.isFinite(saved) && saved >= MIN && saved <= MAX) {
    root.style.setProperty("--sidebar-width", saved + "px");
  }

  let dragging = false;
  let pendingResize = null;

  function applyWidth(px) {
    const w = Math.max(MIN, Math.min(MAX, px));
    root.style.setProperty("--sidebar-width", w + "px");
    if (cy && !pendingResize) {
      // Throttle cy.resize() to one per animation frame for smoothness
      pendingResize = requestAnimationFrame(() => {
        cy.resize();
        pendingResize = null;
      });
    }
  }

  resizer.addEventListener("mousedown", (e) => {
    dragging = true;
    document.body.classList.add("resizing");
    resizer.classList.add("dragging");
    e.preventDefault();
  });

  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    applyWidth(e.clientX);
  });

  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("resizing");
    resizer.classList.remove("dragging");
    const current = parseInt(getComputedStyle(root).getPropertyValue("--sidebar-width"), 10);
    if (Number.isFinite(current)) {
      localStorage.setItem(STORAGE_KEY, String(current));
    }
    if (cy) cy.resize();
  });

  // Double-click to restore default width
  resizer.addEventListener("dblclick", () => {
    root.style.setProperty("--sidebar-width", DEFAULT + "px");
    localStorage.removeItem(STORAGE_KEY);
    if (cy) cy.resize();
  });
}

function setMode(next) {
  mode = next;
  document.getElementById("mode-app").classList.toggle("active", mode === "app");
  document.getElementById("mode-contract").classList.toggle("active", mode === "contract");
  document.getElementById("contract-filters").classList.toggle("hidden", mode !== "contract");
  document.getElementById("app-filters").classList.toggle("hidden", mode !== "app");
  cy.style().fromJson(styleForMode(mode)).update();
  render();
}

function renderStats(graph) {
  const el = document.getElementById("stats");
  if (mode === "app") {
    const parts = [`${graph.stats.apps} apps`, `${graph.stats.edges_total} app-to-app edges`];
    for (const [k, v] of Object.entries(graph.stats.by_kind || {})) parts.push(`${v} ${k.toLowerCase()}`);
    el.textContent = parts.join(" · ");
  } else {
    const s = graph.stats;
    const parts = [`${s.nodes_total} nodes`, `${s.edges_total} edges`];
    if (s.by_label?.Application) parts.push(`${s.by_label.Application} apps`);
    el.textContent = parts.join(" · ");
  }
}

function renderSidebar() {
  const listEl = document.getElementById("app-list");
  const teamEl = document.getElementById("team-filter");
  const platformEl = document.getElementById("platform-filter");
  const hintEl = document.getElementById("archived-hint");
  const teams = new Set();
  const platforms = new Set();
  listEl.innerHTML = "";

  const visible = showArchived ? appsList : appsList.filter((a) => !a.archived);
  const archivedCount = appsList.filter((a) => a.archived).length;

  for (const a of visible) {
    if (a.team) teams.add(a.team);
    if (a.platform) platforms.add(a.platform);
    const li = document.createElement("li");
    li.dataset.name = a.name;
    if (a.archived) li.classList.add("archived");
    const renameNote = a.renamed_to ? ` → <span class="team">renamed to ${a.renamed_to}</span>` : "";
    const platformBadge = a.platform
      ? `<span class="team" style="background:${PLATFORM_BG[a.platform] || "transparent"};color:${PLATFORM_FG[a.platform] || "#666"};padding:0 4px;border-radius:3px;border:0;">${a.platform}</span>`
      : "";
    li.innerHTML = `
      <span class="name">${a.name}${renameNote}</span>
      <span>
        ${platformBadge}
        <span class="team">${a.team || "—"}</span>
        ${a.tier != null ? `<span class="tier">T${a.tier}</span>` : ""}
      </span>`;
    li.addEventListener("click", () => {
      const node = cy.$(`node[name = "${a.name}"][label = "Application"]`);
      if (node.nonempty()) {
        cy.animate({ center: { eles: node }, zoom: 1.1 }, { duration: 300 });
        selectNode(node);
      }
    });
    listEl.appendChild(li);
  }

  // Filters — only refresh when first populated (avoid duplicate <option>s)
  if (teamEl.options.length <= 1) {
    for (const t of [...teams].sort()) {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      teamEl.appendChild(opt);
    }
  }
  if (platformEl.options.length <= 1) {
    for (const p of [...platforms].sort()) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      platformEl.appendChild(opt);
    }
  }

  hintEl.textContent = archivedCount
    ? `${archivedCount} archived app${archivedCount > 1 ? "s" : ""} in the graph.`
    : "No archived apps.";
}

const PLATFORM_BG = {
  azure:    "rgba(0,120,212,0.14)",
  "on-prem": "rgba(75,85,99,0.14)",
  library:  "rgba(180,180,180,0.18)",
};
const PLATFORM_FG = {
  azure:    "#075985",
  "on-prem": "#374151",
  library:  "#4B5563",
};

function render() {
  const team = document.getElementById("team-filter").value;
  const platform = document.getElementById("platform-filter").value;

  let filteredNodes, filteredEdges, graphForStats;

  if (mode === "app") {
    const activeKinds = new Set();
    for (const k of ["REST", "EVENT", "DB", "FILE", "LIB"]) {
      if (document.getElementById(`toggle-kind-${k}`)?.checked) activeKinds.add(k);
    }
    graphForStats = appGraph;
    filteredNodes = appGraph.nodes.filter((n) => {
      if (team && n.data.team !== team) return false;
      if (platform && n.data.platform !== platform) return false;
      return true;
    });
    const allowedIds = new Set(filteredNodes.map((n) => n.data.id));
    filteredEdges = appGraph.edges.filter((e) =>
      activeKinds.has(e.data.kind) && allowedIds.has(e.data.source) && allowedIds.has(e.data.target)
    );
  } else {
    const activeLabels = new Set();
    for (const kind of Object.keys(NODE_COLORS)) {
      if (document.getElementById(`toggle-${kind}`)?.checked) activeLabels.add(kind);
    }
    graphForStats = contractGraph;
    const nodeSet = new Set();
    for (const n of contractGraph.nodes) {
      const d = n.data;
      if (!activeLabels.has(d.label)) continue;
      if (platform && d.label === "Application" && d.platform !== platform) continue;
      if (team && d.label === "Application" && d.team !== team) continue;
      nodeSet.add(d.id);
    }
    filteredNodes = contractGraph.nodes.filter((n) => nodeSet.has(n.data.id));
    filteredEdges = contractGraph.edges.filter(
      (e) => nodeSet.has(e.data.source) && nodeSet.has(e.data.target)
    );
  }

  cy.elements().remove();
  cy.add(filteredNodes);
  cy.add(filteredEdges);
  cy.layout(LAYOUT).run();

  renderStats(graphForStats);

  document.querySelectorAll("#app-list li").forEach((li) => {
    li.classList.toggle("active", li.dataset.name === selectedAppName);
  });
}

function selectNode(node) {
  cy.elements().removeClass("highlight dim impact impact-edge");
  node.addClass("highlight");
  const neighborhood = node.closedNeighborhood();
  cy.elements().difference(neighborhood).addClass("dim");

  const d = node.data();
  selectedAppName = d.label === "Application" ? d.name : null;
  document.querySelectorAll("#app-list li").forEach((li) => {
    li.classList.toggle("active", li.dataset.name === selectedAppName);
  });

  document.getElementById("selected-panel").classList.remove("hidden");
  document.getElementById("selected-detail").innerHTML = formatNode(d);

  document.getElementById("impact-downstream").disabled = d.label !== "Application";
  document.getElementById("impact-upstream").disabled = d.label !== "Application";
  document.getElementById("generate-docs").disabled = d.label !== "Application";

  // Clear any stale autodoc status when picking a new node
  const statusEl = document.getElementById("autodoc-status");
  statusEl.className = "autodoc-status";
  statusEl.textContent = "";
}

function deselect() {
  cy.elements().removeClass("highlight dim impact impact-edge");
  selectedAppName = null;
  document.getElementById("selected-panel").classList.add("hidden");
  document.querySelectorAll("#app-list li").forEach((li) => li.classList.remove("active"));
}

function formatNode(d) {
  const rows = [];
  rows.push(`<b>${d.label}</b>  ${d.name || d.id}`);
  for (const [k, v] of Object.entries(d)) {
    if (["id", "label", "name"].includes(k)) continue;
    if (v == null || v === "") continue;
    rows.push(`${k.padEnd(12)} ${String(v)}`);
  }
  return rows.join("\n");
}

async function showImpact(direction) {
  if (!selectedAppName) return;
  const data = await fetch(`/api/impact/${encodeURIComponent(selectedAppName)}?direction=${direction}`).then((r) => r.json());
  cy.elements().removeClass("impact impact-edge highlight dim");

  const affected = new Set(data.affected_apps);
  cy.nodes().forEach((n) => {
    const d = n.data();
    if (d.label === "Application" && (affected.has(d.name) || d.name === selectedAppName)) {
      n.addClass("impact");
    } else {
      n.addClass("dim");
    }
  });
  cy.edges().forEach((e) => {
    const s = cy.getElementById(e.data("source"));
    const t = cy.getElementById(e.data("target"));
    if (s.hasClass("impact") && t.hasClass("impact")) e.addClass("impact-edge");
    else e.addClass("dim");
  });
}

function clearImpact() {
  cy.elements().removeClass("impact impact-edge dim highlight");
}

async function generateDocs() {
  if (!selectedAppName) return;
  const statusEl = document.getElementById("autodoc-status");
  const btn = document.getElementById("generate-docs");

  statusEl.className = "autodoc-status visible info";
  statusEl.innerHTML =
    `⏳ Generating docs for <b>${selectedAppName}</b>… (clone + LLM + MR, usually 5–20s)`;
  btn.disabled = true;

  try {
    const r = await fetch(
      `/api/autodoc/trigger/${encodeURIComponent(selectedAppName)}`,
      { method: "POST" },
    );
    if (!r.ok) {
      const body = await r.text().catch(() => `HTTP ${r.status}`);
      throw new Error(body || `HTTP ${r.status}`);
    }
    const data = await r.json();
    if (data.action === "error") throw new Error(data.message || "unknown error");
    if (data.action === "no_change") {
      statusEl.className = "autodoc-status visible info";
      statusEl.innerHTML = `ℹ️ README already matches Sherlock's generated content. No MR needed.`;
      return;
    }
    if (data.mr_url) {
      const verb = data.action === "updated" ? "refreshed" : "opened";
      statusEl.className = "autodoc-status visible success";
      statusEl.innerHTML =
        `✅ MR !${data.mr_iid} ${verb}. ` +
        `<a href="${data.mr_url}" target="_blank" rel="noopener">Open in GitLab ↗</a>`;
      window.open(data.mr_url, "_blank", "noopener");
    } else {
      statusEl.className = "autodoc-status visible info";
      statusEl.innerHTML = `ℹ️ ${data.action}: ${data.message || "(no URL returned)"}`;
    }
  } catch (err) {
    statusEl.className = "autodoc-status visible error";
    statusEl.innerHTML = `❌ Autodoc failed: ${err.message || err}`;
  } finally {
    btn.disabled = false;
  }
}

init();
