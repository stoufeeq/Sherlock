#!/usr/bin/env bash
# Sherlock pre-push impact check.
#
# Run this from inside a fixture repo's working tree (or any repo Sherlock is
# tracking). Computes the diff between HEAD and the base ref (default: origin/main),
# uploads it to /analyze-diff, and prints a coloured summary of the downstream
# impact BEFORE you push.
#
# Install as a git pre-push hook:
#   ln -s "$(realpath scripts/sherlock-impact-check.sh)" .git/hooks/pre-push
#
# Or just call it ad-hoc:
#   ./scripts/sherlock-impact-check.sh                  # default app = repo dir name
#   ./scripts/sherlock-impact-check.sh account-service  # explicit app name
#
# Env knobs:
#   SHERLOCK_URL       default http://localhost:8001
#   SHERLOCK_BASE_REF  default origin/main
#   SHERLOCK_APP       default = basename of git toplevel
#   SHERLOCK_BLOCK     when "true", non-zero exit on breaking changes (hooks default off)

set -euo pipefail

SHERLOCK_URL="${SHERLOCK_URL:-http://localhost:8001}"
SHERLOCK_BASE_REF="${SHERLOCK_BASE_REF:-origin/main}"
SHERLOCK_BLOCK="${SHERLOCK_BLOCK:-false}"

# Colours — disable on non-tty
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_GREEN=$'\033[32m'
  C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_RED=""; C_YELLOW=""; C_GREEN=""; C_BOLD=""; C_DIM=""; C_RESET=""
fi

die()  { echo "${C_RED}${C_BOLD}sherlock:${C_RESET} $*" >&2; exit 1; }
info() { echo "${C_DIM}sherlock:${C_RESET} $*"; }

command -v git >/dev/null  || die "git not found on PATH"
command -v curl >/dev/null || die "curl not found on PATH"
command -v jq >/dev/null   || die "jq not found on PATH (brew install jq / apt install jq)"

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Detect pre-push hook invocation. Git passes "$1=<remote-name>" and
# "$2=<remote-URL>" — when $2 looks like a URL, ignore both and fall back to
# the repo basename as the app name. In ad-hoc mode the user can override
# with $1 or with SHERLOCK_APP.
if [ "${2:-}" ] && printf '%s' "$2" | grep -qE '^(https?://|git@|ssh://)'; then
  APP_NAME="${SHERLOCK_APP:-$(basename "$REPO_ROOT")}"
else
  APP_NAME="${1:-${SHERLOCK_APP:-$(basename "$REPO_ROOT")}}"
fi

# Make sure the base ref exists (fetch if needed)
if ! git rev-parse --verify --quiet "$SHERLOCK_BASE_REF" >/dev/null; then
  info "fetching $SHERLOCK_BASE_REF…"
  git fetch --quiet origin "$(echo "$SHERLOCK_BASE_REF" | sed 's|^origin/||')" || \
    die "could not fetch $SHERLOCK_BASE_REF"
fi

# Files changed in HEAD relative to base, plus unstaged/uncommitted working-tree
# changes. macOS ships bash 3.2 (no `mapfile`), so collect into newline-delimited
# strings rather than arrays.
CHANGED="$(
  {
    git diff --name-only --diff-filter=ACMR "$SHERLOCK_BASE_REF"...HEAD
    git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null || true
  } | awk 'NF && !seen[$0]++'
)"
DELETED="$(
  git diff --name-only --diff-filter=D "$SHERLOCK_BASE_REF"...HEAD | awk 'NF && !seen[$0]++'
)"

CHANGED_COUNT=0
[ -n "$CHANGED" ] && CHANGED_COUNT="$(printf '%s\n' "$CHANGED" | wc -l | tr -d ' ')"
DELETED_COUNT=0
[ -n "$DELETED" ] && DELETED_COUNT="$(printf '%s\n' "$DELETED" | wc -l | tr -d ' ')"

if [ "$CHANGED_COUNT" -eq 0 ] && [ "$DELETED_COUNT" -eq 0 ]; then
  echo "${C_GREEN}sherlock:${C_RESET} no changes vs $SHERLOCK_BASE_REF — nothing to analyse."
  exit 0
fi

info "app=$APP_NAME  base=$SHERLOCK_BASE_REF  changed=$CHANGED_COUNT  deleted=$DELETED_COUNT"

# Build the JSON payload — `working_files` is a {path: content} map.
# Start with empty maps; we add one file at a time so jq handles all escaping.
TMPJSON="$(mktemp -t sherlock-payload.XXXXXX)"
trap 'rm -f "$TMPJSON" "$TMPJSON.next" 2>/dev/null' EXIT

DELETED_JSON="$(printf '%s\n' "$DELETED" | jq -R -s -c 'split("\n")|map(select(length>0))')"
jq -n \
  --arg app "$APP_NAME" \
  --arg base "${SHERLOCK_BASE_REF#origin/}" \
  --argjson deleted "$DELETED_JSON" \
  '{
     app_name: $app,
     base_ref: $base,
     working_files: {},
     deleted_files: $deleted
   }' > "$TMPJSON"

# Inline file contents one at a time so jq can read each via --rawfile.
if [ -n "$CHANGED" ]; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if [ -f "$REPO_ROOT/$f" ]; then
      jq --arg path "$f" --rawfile content "$REPO_ROOT/$f" \
         '.working_files[$path] = $content' "$TMPJSON" > "$TMPJSON.next"
      mv "$TMPJSON.next" "$TMPJSON"
    fi
  done <<EOF
$CHANGED
EOF
fi

RESPONSE="$(curl -sS -X POST "$SHERLOCK_URL/analyze-diff" \
  -H 'Content-Type: application/json' \
  --data-binary "@$TMPJSON" )"

# Sanity-check
if ! echo "$RESPONSE" | jq -e . >/dev/null 2>&1; then
  echo "${C_RED}sherlock:${C_RESET} unexpected response from $SHERLOCK_URL"
  echo "$RESPONSE"
  exit 0   # don't block the push on infra failures
fi
if echo "$RESPONSE" | jq -e '.detail' >/dev/null; then
  echo "${C_YELLOW}sherlock:${C_RESET} $(echo "$RESPONSE" | jq -r .detail)"
  exit 0
fi

BREAKING="$(echo "$RESPONSE" | jq -r '.summary.breaking')"
INFO_CT="$(echo "$RESPONSE" | jq -r '.summary.info')"
AFFECTED="$(echo "$RESPONSE" | jq -r '.summary.affected_apps')"
CROSS="$(echo "$RESPONSE" | jq -r '.summary.cross_platform')"
PLATFORM="$(echo "$RESPONSE" | jq -r '.source_platform // "?"')"

echo
echo "${C_BOLD}🔎 Sherlock impact analysis${C_RESET}  ${C_DIM}($APP_NAME · platform $PLATFORM · base $SHERLOCK_BASE_REF)${C_RESET}"
echo

if [ "$BREAKING" -eq 0 ] && [ "$INFO_CT" -eq 0 ]; then
  echo "${C_GREEN}✓ no cross-application breaking changes detected${C_RESET}"
  echo
  exit 0
fi

if [ "$BREAKING" -gt 0 ]; then
  echo "${C_RED}${C_BOLD}⚠  $BREAKING breaking change(s)${C_RESET}  ·  $AFFECTED app(s) affected"
fi
if [ "$INFO_CT" -gt 0 ]; then
  echo "${C_YELLOW}ℹ  $INFO_CT additive / info-only change(s)${C_RESET}"
fi
if [ "$CROSS" -gt 0 ]; then
  echo "${C_RED}🚨 $CROSS cross-platform impact(s) — Azure ↔ on-prem boundary${C_RESET}"
fi
echo

# Per-break detail
echo "$RESPONSE" | jq -r --arg b "$C_BOLD" --arg r "$C_RESET" '
  .breaks[] |
  "  " + $b + .kind + $r + "  " + (.detail // "") +
  (
    if (.impacted | length) > 0 then
      "\n    " + (.impacted | map(.name + " (" + (.team // "?") + ", T" + ((.tier // "?") | tostring) + (if .platform then ", " + .platform else "" end) + (if .confidence == "heuristic" then ", heuristic" else "" end) + ")") | join("\n    "))
    else ""
    end
  )
'
echo
echo "${C_DIM}Sherlock informs — it does not block merges. Coordinate with the teams above before pushing.${C_RESET}"

if [ "$SHERLOCK_BLOCK" = "true" ] && [ "$BREAKING" -gt 0 ]; then
  exit 1
fi
exit 0
