# Sherlock CTO pitch deck

Output: `Sherlock_CTO_Pitch.pptx` at the repo root (27 slides: 17 main + 10 appendix).

## Regenerate

```bash
cd tools/deck
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python generate.py
```

## Before presenting — do these five things

1. **Replace the UBS logo placeholder.** Every slide has a top-left text-mark: three small red bars + "UBS" letters. Replace with the official brand asset from UBS Brand Hub:
   - Select the group on slide 1, Delete.
   - Insert → Picture → the official SVG/PNG.
   - Repeat for slide 2 onwards, or use the Slide Master (View → Slide Master) to replace once in the master and propagate.
2. **Drop in canvas screenshots.** The canvas slide references `http://localhost:8001/ui/`. Placeholder marked `[ insert canvas screenshot ... ]` — replace with a 16:9 screenshot of:
   - **App view** with `transaction-service` selected and **Downstream impact →** active (orange cascade).
3. **Swap the font if UBS Sans / Frutiger UBS is installed on your laptop.** Open `generate.py`, change `FONT_SANS = "Arial"` → `FONT_SANS = "UBS Sans"` (or the exact name on your system), regenerate.
4. **Fill in a specific incident.** Slide 3 uses composite illustrative patterns. If you get clearance to cite a real incident (anonymized is fine), add it as a fourth card or swap one of the existing three — a real incident with duration + customer/ops cost massively increases the pitch's impact.
5. **Confirm the scale numbers.** Slides 2 and 3 say "10,000+ engineers, 17 domains, thousands of repos". Adjust to the exact figures you want to use.

## Slide map

### Main (17 slides)
| # | Slide | Purpose |
|---|-------|---------|
| 1 | Title | Sherlock · Dependency Intelligence Platform |
| 2 | Executive summary | Problem / Solution / Ask — one-slide takeaway |
| 3 | The problem | Three recurring cross-app break patterns |
| 4 | Visibility gap | Why CMDB / APM / Backstage / Sourcegraph don't close it |
| 5 | Introducing Sherlock | SEE · PREDICT · NOTIFY |
| 6 | Architecture | GitLab → Ingest → Analyzers → Graph → Notifier |
| 7 | Detection coverage | REST · Events · DB · File feeds · Libraries (COBOL highlighted) |
| 8 | MR comment (author) | Impact report posted on the AUTHOR's own breaking MR |
| 9 | The canvas | Enterprise topology, App view + Contract view |
| 10 | Sticky impact tags (downstream) | Issues opened in AFFECTED repos, auto-close on fix |
| 11 | **Auto-documentation (owning team)** | Draft README MR in the APP's OWN repo — Gemini/Azure OpenAI |
| 12 | Proof of concept | POC numbers (now includes autodoc + auto-discovery) |
| 13 | Roadmap | H1 POC ✓ · H2 started · H3 · H4 |
| 14 | Pilot plan | 3 months — operationalize, embed, roll out first domain |
| 15 | The ask | Funded pilot · 2–3 FTEs · platform embed · sponsor |
| 16 | Success metrics | MTTD · engagement · sticky cycle time · coverage |
| 17 | Closing | "Every change has a blast radius." |

### Appendix (10 slides)
| # | Slide | Purpose |
|---|-------|---------|
| 18 | Divider | "Deeper dives for Q&A" |
| 19 | A1 — Deeper architecture | Component-by-component |
| 20 | A2 — Coverage detail | What's covered + known gaps (roadmap) |
| 21 | A3 — Graph schema | 7 node types, 12 edge types |
| 22 | A4 — Security / residency / PII | "Code, not data" |
| 23 | A5 — H2 LLM autodoc | Deeper on cost control, caching, audit |
| 24 | A6 — Integration futures | CMDB · Backstage · APM · Slack · GitLab app |
| 25 | A7 — Competitive positioning | vs. Backstage / Dependabot / APM / Sourcegraph / Sonar |
| 26 | **A8 — Operator features** | Auto-discovery · multi-group · parallel scan · rename · archival |
| 27 | A9 — Why now · why UBS · why us | Closing appendix |

## Slides 8, 10, 11 — the three different "outputs" (important distinction)

This is the part that historically caused confusion, including in earlier versions of this deck. The three slides show three **separate** flows:

- **Slide 8 (MR comment for the author).** Fires when a breaking change is opened. Lands on the **author's own MR**. Reviewed by the author's team.
- **Slide 10 (Sticky impact tag for affected teams).** Fires for the same breaking change. Lands as an **`impact::pending` issue in each downstream repo**. Reviewed by the owning teams of the affected apps.
- **Slide 11 (Autodoc MR for the owning team).** Fires on a schedule or manual trigger, *independent* of any breaking change. Lands as a **draft README MR in that same app's own repo**. Reviewed by the app's own team.

If asked "doesn't autodoc push to downstream repos?" — **no**, that's Slide 10. Slide 11 stays local to the owning repo.

## Pacing (30-minute slot)

- Slides 1–2: 2 min (title + one-slide takeaway)
- Slides 3–4: 4 min (problem + gap)
- Slides 5–7: 5 min (solution + architecture + coverage)
- Slides 8–11: 8 min (MR comment → canvas → sticky tags → autodoc — the four "aha" moments, cleanly separated)
- Slides 12–14: 5 min (POC proof + roadmap + pilot plan)
- Slide 15: 2 min (the ask — stop and listen)
- Slides 16–17: 2 min (metrics + close)

Leaves ~12–15 minutes for Q&A. Most likely questions and where to turn:
- "How does this relate to Backstage / Dynatrace / Sourcegraph?" → **Slide 25 (A7)**
- "What about security / PII?" → **Slide 22 (A4)**
- "When does the LLM piece land? How do costs scale?" → **Slide 23 (A5)**
- "How does it scale to 10,000 repos?" → **Slide 26 (A8 operator features)**
- "How does the platform team operate this?" → **Slide 26 (A8)**
- "Why not replace CMDB?" → **Slide 24 (A6)** — CMDB is read-only input
- "Isn't autodoc going to PR every downstream team?" → **NO** — re-explain slides 10 vs 11 distinction (see above)

## Speaker notes

Every slide has speaker notes in the Notes pane. Reveal with View → Notes.
