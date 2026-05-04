# Sherlock Impact — VS Code extension (MVP)

Surfaces the same impact analysis the Sherlock MR bot runs, **inside the
IDE**, before the change is committed or pushed.

| Surface | Behaviour |
|---|---|
| **Status bar** | Always visible. Click to run analysis — turns amber on breaking changes. |
| **Command palette** | `Sherlock: Analyze Impact of Pending Changes` and `Sherlock: Open Last Impact Report`. |
| **Webview report** | Opens beside the editor — shows breaks, affected apps, on-call channel, cross-platform 🚨 banner. |
| **Auto-on-save** | Off by default. Enable `sherlock.analyzeOnSave` to debounce + analyze 1s after each save. |

Everything goes through the existing `POST /analyze-diff` endpoint — no new
backend code, same engine as the pre-push hook and the MR bot.

## Settings

| Key | Default | Notes |
|---|---|---|
| `sherlock.endpoint` | `http://localhost:8001` | Sherlock service URL, no trailing slash |
| `sherlock.baseRef` | `origin/main` | Diff target — endpoint clones this ref and overlays your working tree |
| `sherlock.appName` | *(blank)* | Override the app name; defaults to the workspace folder basename |
| `sherlock.token` | *(blank)* | Optional `Authorization: Bearer …` token for production deployments |
| `sherlock.analyzeOnSave` | `false` | Auto-analyze on every save (1s debounce) |

## Install (sideload)

The extension is a single `.vsix` you install with the VS Code CLI. No
Marketplace dependency — works equally well in **VS Code, Cursor, Windsurf,
and Antigravity** because they're all VS Code forks with the same extension API.

```bash
# 1. Build the .vsix (no global install — npx fetches @vscode/vsce on demand)
cd tools/vscode-sherlock
npx --yes @vscode/vsce package --no-dependencies     # → sherlock-impact-<version>.vsix

# 2. Install it
code     --install-extension ./sherlock-impact-0.1.0.vsix    # VS Code
cursor   --install-extension ./sherlock-impact-0.1.0.vsix    # Cursor
windsurf --install-extension ./sherlock-impact-0.1.0.vsix    # Windsurf
# Antigravity: same CLI flag, or drag-drop the .vsix into the Extensions side bar
```

Or `make extension-package` from the repo root (does steps 1+2 in one go).

## Develop

Open `tools/vscode-sherlock/` in VS Code, press `F5`. A second VS Code window
launches with the extension loaded; open one of the fixture repos in it
(`fixtures/account-service/` is the easiest to demo) and run
`Sherlock: Analyze Impact of Pending Changes` from the command palette.

The extension itself has zero runtime dependencies (uses only the bundled VS
Code API + Node built-ins), so iteration is just edit-and-reload — no `npm
install` step inside the extension folder.

## Roadmap (Phase B)

- Inline diagnostics in the **Problems panel** for each removed endpoint /
  changed contract — rendered against the file the analyzer flagged.
- **CodeLens** above OpenAPI endpoint definitions: *"used by mobile-bff,
  fraud-detection (and 1 more)"*.
- **Quick-fix** action that opens the affected app's repo in a new window.
- **Auth via GitLab OIDC** — replace PAT-style tokens once Sherlock graduates
  from the GitLab PAT to a proper GitLab App.
