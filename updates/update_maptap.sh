#!/bin/bash
# update_maptap.sh
# Extracts Maptap scores from iMessage and pushes to GitHub.
# Run manually or via cron — see README for setup instructions.

set -euo pipefail

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
REPO_DIR="$HOME/github/marcstern14/maptap-scoreboard"
# ──────────────────────────────────────────────────────────────────────────────

# Ensure python3/git are available when run from launchd (minimal PATH)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.pyenv/shims:$HOME/.pyenv/versions/3.12.7/bin:$PATH"

SCRIPT="$REPO_DIR/updates/extract_maptap.py"
LOG="$REPO_DIR/update.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "── Maptap daily update starting ──"

# Skip if we already ran successfully today
TODAY=$(date '+%Y-%m-%d')
MARKER="$REPO_DIR/.last-update"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0
fi

# Sanity checks
if [ ! -d "$REPO_DIR" ]; then
  log "ERROR: REPO_DIR not found: $REPO_DIR"
  log "Edit the REPO_DIR variable at the top of this script."
  exit 1
fi

if [ ! -f "$SCRIPT" ]; then
  log "ERROR: extract_maptap.py not found at $SCRIPT"
  exit 1
fi

cd "$REPO_DIR"

DB_COPY=$(mktemp /tmp/maptap-chat-XXXXXX.db)
cp "$HOME/Library/Messages/chat.db" "$DB_COPY"
export MAPTAP_DB_COPY="$DB_COPY"

log "Running extractor…"
if ! python3 "$SCRIPT" >> "$LOG" 2>&1; then
  rm -f "$DB_COPY"
  log "ERROR: extractor failed."
  exit 1
fi
rm -f "$DB_COPY"

# Check scores.json was actually updated
if [ ! -f "$REPO_DIR/scores.json" ]; then
  log "ERROR: scores.json was not produced."
  exit 1
fi

# Git: stage, commit, push
log "Pushing to GitHub…"
git add scores.json
if git diff --cached --quiet; then
  log "No new scores since last update — nothing to push."
  exit 0
fi

git commit -m "chore: update scores $(date '+%Y-%m-%d')"

if ! git push >> "$LOG" 2>&1; then
  log "ERROR: git push failed. Check your remote and credentials."
  exit 1
fi

log "Done. scores.json pushed to GitHub."

echo "$TODAY" > "$MARKER"
log "── Update complete ──"