// Sherlock Impact — VS Code extension MVP.
//
// Surfaces the same /analyze-diff result the pre-push hook prints, but inside
// the IDE: status-bar count + command-palette trigger + webview report. No
// dependencies beyond the bundled VS Code API and Node's built-in modules, so
// the .vsix installs cleanly on VS Code, Cursor, Windsurf, and Antigravity
// without an npm step.

const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const http = require("http");
const https = require("https");
const { URL } = require("url");

// ---- module-level state ----------------------------------------------------

let statusItem;          // vscode.StatusBarItem — always visible when active
let lastReport = null;   // most recent /analyze-diff JSON, for "open last report"
let lastWebview = null;  // active webview panel, reused between runs
let saveTimer = null;    // debounce timer for analyzeOnSave

// ---- entry point -----------------------------------------------------------

function activate(context) {
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusItem.command = "sherlock.analyzeImpact";
  setStatus("idle");
  statusItem.show();
  context.subscriptions.push(statusItem);

  context.subscriptions.push(
    vscode.commands.registerCommand("sherlock.analyzeImpact", () => analyzeImpact(false)),
    vscode.commands.registerCommand("sherlock.openLastReport", openLastReport),
    vscode.workspace.onDidSaveTextDocument(onDocumentSaved),
  );
}

function deactivate() {
  if (saveTimer) clearTimeout(saveTimer);
}

// ---- commands --------------------------------------------------------------

async function analyzeImpact(silent) {
  const folder = currentWorkspaceFolder();
  if (!folder) {
    if (!silent) vscode.window.showWarningMessage("Sherlock: open a workspace folder first.");
    return;
  }

  const cfg = vscode.workspace.getConfiguration("sherlock");
  const endpoint = (cfg.get("endpoint") || "").replace(/\/+$/, "");
  if (!endpoint) {
    vscode.window.showErrorMessage("Sherlock: configure 'sherlock.endpoint' (e.g. http://localhost:8001).");
    return;
  }
  const baseRef  = cfg.get("baseRef")  || "origin/main";
  const token    = cfg.get("token")    || "";
  const appName  = (cfg.get("appName") || "").trim() || path.basename(folder.uri.fsPath);

  setStatus("scanning");

  let diff;
  try {
    diff = await collectDiff(folder.uri.fsPath, baseRef);
  } catch (err) {
    setStatus("error");
    vscode.window.showErrorMessage(`Sherlock: git diff failed — ${err.message}`);
    return;
  }
  if (diff.changed.length === 0 && diff.deleted.length === 0) {
    setStatus("clean");
    if (!silent) vscode.window.showInformationMessage(`Sherlock: no changes vs ${baseRef}.`);
    return;
  }

  const payload = {
    app_name: appName,
    base_ref: baseRef.replace(/^origin\//, ""),
    working_files: diff.workingFiles,
    deleted_files: diff.deleted,
  };

  let response;
  try {
    response = await postJson(`${endpoint}/analyze-diff`, payload, token);
  } catch (err) {
    setStatus("error");
    vscode.window.showErrorMessage(`Sherlock: ${err.message}`);
    return;
  }

  if (response.detail) {
    setStatus("error");
    vscode.window.showWarningMessage(`Sherlock: ${response.detail}`);
    return;
  }

  lastReport = response;
  const summary = response.summary || {};
  const breaking = summary.breaking || 0;
  const info     = summary.info     || 0;
  const xplat    = summary.cross_platform || 0;

  setStatus(breaking > 0 ? "breaking" : info > 0 ? "info" : "clean", { breaking, info, xplat });

  // Auto-open the report on demand; on auto-trigger only flash the status bar.
  if (!silent) {
    openLastReport();
  }
}

function openLastReport() {
  if (!lastReport) {
    vscode.window.showInformationMessage("Sherlock: no analysis run yet — invoke 'Analyze Impact of Pending Changes' first.");
    return;
  }
  if (lastWebview) {
    lastWebview.reveal(vscode.ViewColumn.Beside);
    lastWebview.webview.html = renderReportHtml(lastReport);
    return;
  }
  lastWebview = vscode.window.createWebviewPanel(
    "sherlockImpact",
    "Sherlock — Impact",
    vscode.ViewColumn.Beside,
    { enableScripts: false, retainContextWhenHidden: true },
  );
  lastWebview.onDidDispose(() => { lastWebview = null; });
  lastWebview.webview.html = renderReportHtml(lastReport);
}

// ---- helpers: git ----------------------------------------------------------

// Returns { changed: [paths], deleted: [paths], workingFiles: { path: content } }
async function collectDiff(repoRoot, baseRef) {
  // Make sure the base ref actually exists locally; if not, fetch the matching branch.
  try {
    await runGit(repoRoot, ["rev-parse", "--verify", "--quiet", baseRef]);
  } catch (_) {
    const branch = baseRef.replace(/^origin\//, "");
    await runGit(repoRoot, ["fetch", "--quiet", "origin", branch]);
  }

  // Collect committed + uncommitted ACMR (added/copied/modified/renamed) and Deleted.
  const committed = await runGit(repoRoot, ["diff", "--name-only", "--diff-filter=ACMR", `${baseRef}...HEAD`]);
  let uncommitted = "";
  try {
    uncommitted = await runGit(repoRoot, ["diff", "--name-only", "--diff-filter=ACMR", "HEAD"]);
  } catch (_) { /* HEAD may not exist on a fresh repo */ }
  const deletedRaw = await runGit(repoRoot, ["diff", "--name-only", "--diff-filter=D", `${baseRef}...HEAD`]);

  const dedup = (s) => Array.from(new Set(s.split("\n").map((x) => x.trim()).filter(Boolean)));
  const changed = dedup(committed + "\n" + uncommitted);
  const deleted = dedup(deletedRaw);

  // Read each changed file's current contents from the working tree.
  const workingFiles = {};
  const fs = require("fs");
  for (const rel of changed) {
    const full = path.join(repoRoot, rel);
    try {
      // Skip obviously-binary suffixes — analyzers ignore them anyway and they
      // bloat the request body.
      if (looksBinary(rel)) continue;
      workingFiles[rel] = fs.readFileSync(full, "utf8");
    } catch (_) {
      // file may have been moved/renamed since git diff snapshot — skip it
    }
  }
  return { changed, deleted, workingFiles };
}

function looksBinary(rel) {
  const denied = [".class", ".jar", ".war", ".pyc", ".so", ".dll",
                  ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz"];
  const ext = path.extname(rel).toLowerCase();
  return denied.includes(ext);
}

function runGit(cwd, args) {
  return new Promise((resolve, reject) => {
    cp.execFile("git", args, { cwd, maxBuffer: 16 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) {
        const msg = stderr ? stderr.toString().trim() : err.message;
        return reject(new Error(`git ${args.join(" ")} → ${msg}`));
      }
      resolve(stdout.toString());
    });
  });
}

function currentWorkspaceFolder() {
  const folders = vscode.workspace.workspaceFolders || [];
  if (folders.length === 0) return null;
  // If there's an active editor, prefer the folder it belongs to (multi-root workspaces).
  const active = vscode.window.activeTextEditor?.document?.uri;
  if (active) {
    const f = vscode.workspace.getWorkspaceFolder(active);
    if (f) return f;
  }
  return folders[0];
}

// ---- helpers: HTTP ---------------------------------------------------------

function postJson(url, body, token) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const data = Buffer.from(JSON.stringify(body), "utf8");
    const headers = { "Content-Type": "application/json", "Content-Length": data.length };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const opts = {
      method: "POST",
      hostname: u.hostname,
      port: u.port || (u.protocol === "https:" ? 443 : 80),
      path: u.pathname + (u.search || ""),
      headers,
    };
    const lib = u.protocol === "https:" ? https : http;
    const req = lib.request(opts, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        try {
          resolve(JSON.parse(text));
        } catch (e) {
          reject(new Error(`non-JSON response (HTTP ${res.statusCode}): ${text.slice(0, 200)}`));
        }
      });
    });
    req.on("error", (e) => reject(new Error(`request failed: ${e.message}`)));
    req.write(data);
    req.end();
  });
}

// ---- helpers: status bar ---------------------------------------------------

function setStatus(state, counts) {
  switch (state) {
    case "idle":
      statusItem.text = "$(search) Sherlock";
      statusItem.tooltip = "Click to analyze the working-tree impact via Sherlock.";
      statusItem.backgroundColor = undefined;
      return;
    case "scanning":
      statusItem.text = "$(sync~spin) Sherlock: scanning…";
      statusItem.tooltip = "Posting working-tree diff to /analyze-diff…";
      statusItem.backgroundColor = undefined;
      return;
    case "clean":
      statusItem.text = "$(pass-filled) Sherlock: no impact";
      statusItem.tooltip = "No cross-application breaking changes detected.";
      statusItem.backgroundColor = undefined;
      return;
    case "info":
      statusItem.text = `$(info) Sherlock: ${counts.info} info`;
      statusItem.tooltip = "Additive / info-only changes only — no required contracts removed.";
      statusItem.backgroundColor = undefined;
      return;
    case "breaking": {
      const x = counts.xplat ? `  ·  🚨 ${counts.xplat}` : "";
      statusItem.text = `$(warning) Sherlock: ${counts.breaking} breaking${x}`;
      statusItem.tooltip = "Click to open the full impact report.";
      statusItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
      return;
    }
    case "error":
      statusItem.text = "$(error) Sherlock: error";
      statusItem.tooltip = "See notification or output panel.";
      statusItem.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
      return;
  }
}

// ---- on-save debouncing ----------------------------------------------------

function onDocumentSaved(doc) {
  const cfg = vscode.workspace.getConfiguration("sherlock");
  if (!cfg.get("analyzeOnSave")) return;
  if (doc.uri.scheme !== "file") return;
  if (saveTimer) clearTimeout(saveTimer);
  // Coalesce burst-saves into one analysis call.
  saveTimer = setTimeout(() => analyzeImpact(true), 1000);
}

// ---- webview HTML ----------------------------------------------------------

function renderReportHtml(report) {
  const summary = report.summary || {};
  const breaking = summary.breaking || 0;
  const info = summary.info || 0;
  const xplat = summary.cross_platform || 0;
  const platform = report.source_platform || "?";

  const banner = breaking > 0
    ? `<div class="banner err">⚠ ${breaking} breaking change${breaking === 1 ? "" : "s"} · ${summary.affected_apps || 0} app${summary.affected_apps === 1 ? "" : "s"} affected</div>`
    : info > 0
      ? `<div class="banner info">ℹ ${info} additive / info-only change${info === 1 ? "" : "s"} — consumers should not break</div>`
      : `<div class="banner ok">✓ no cross-application breaking changes detected</div>`;

  const xplatBanner = xplat > 0
    ? `<div class="banner xplat">🚨 ${xplat} cross-platform impact${xplat === 1 ? "" : "s"} — Azure ↔ on-prem boundary crossing</div>`
    : "";

  const breakRows = (report.breaks || []).map((b) => {
    const apps = (b.impacted || []).map((a) => `
      <li>
        <strong>${escape(a.name)}</strong>
        <span class="muted">team ${escape(a.team || "?")} · tier ${a.tier ?? "?"}${a.platform ? ` · ${escape(a.platform)}` : ""}${a.confidence === "heuristic" ? " · heuristic" : ""}</span>
      </li>
    `).join("");
    return `
      <section class="break">
        <h3><code>${escape(b.kind)}</code> &nbsp; ${escape(b.detail || "")}</h3>
        <ul>${apps || "<li class=\"muted\">No known downstream consumers in the current graph.</li>"}</ul>
      </section>
    `;
  }).join("");

  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 16px 20px; line-height: 1.4; }
    h1 { font-size: 1.3em; margin: 0 0 4px 0; }
    .meta { color: var(--vscode-descriptionForeground); font-size: 0.9em; margin-bottom: 14px; }
    .banner { padding: 8px 12px; border-radius: 4px; margin: 6px 0; font-weight: 600; }
    .banner.ok    { background: rgba(16,185,129,0.15); color: #10B981; }
    .banner.info  { background: rgba(245,158,11,0.15); color: #F59E0B; }
    .banner.err   { background: rgba(236,0,22,0.15);   color: #EC0016; }
    .banner.xplat { background: rgba(236,0,22,0.10);   color: #EC0016; border: 1px solid #EC0016; }
    .break { margin: 14px 0; padding: 10px 12px; border: 1px solid var(--vscode-panel-border); border-radius: 4px; }
    .break h3 { font-size: 1em; margin: 0 0 8px 0; }
    .break code { font-family: var(--vscode-editor-font-family); background: var(--vscode-textBlockQuote-background); padding: 1px 5px; border-radius: 3px; }
    .break ul { margin: 6px 0 0 16px; padding: 0; }
    .break li { margin: 2px 0; }
    .muted { color: var(--vscode-descriptionForeground); font-weight: 400; margin-left: 4px; }
  </style></head><body>
    <h1>🔎 Sherlock Impact</h1>
    <div class="meta">
      ${escape(report.app)} · platform <code>${escape(platform)}</code> · base <code>${escape(report.base_ref)}</code>
      · overlay ${report.overlay?.written || 0} written / ${report.overlay?.deleted || 0} deleted
    </div>
    ${banner}
    ${xplatBanner}
    ${breakRows || ""}
  </body></html>`;
}

function escape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[c]);
}

module.exports = { activate, deactivate };
