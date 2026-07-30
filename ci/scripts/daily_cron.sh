#!/usr/bin/env bash
#
# daily_cron.sh — Orchestrate the full S1 music pipeline
# Run from ~/.openclaw/workspace/music-herebuy/scripts/
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TODAY="$(date +%Y-%m-%d)"
LOG_DIR="$PROJECT_DIR/logs"
MANIFEST_DIR="$PROJECT_DIR/data/manifest"

mkdir -p "$LOG_DIR" "$MANIFEST_DIR"

log() { echo "[$(date '+%H:%M:%S')] $1"; }

log "=== S1 Music Pipeline started: $TODAY ==="

# Step 1: Last.fm
log "[1/5] Fetching Last.fm charts..."
if python3 "$SCRIPT_DIR/lastfm_fetch.py" >> "$LOG_DIR/lastfm_$TODAY.log" 2>&1; then
    log "[1/5] Last.fm OK"
else
    log "[1/5] Last.fm FAILED (check logs)"
    exit 1
fi

# Step 2: Billboard
log "[2/5] Fetching Billboard Hot 100..."
if python3 "$SCRIPT_DIR/billboard_fetch.py" >> "$LOG_DIR/billboard_$TODAY.log" 2>&1; then
    log "[2/5] Billboard OK"
else
    log "[2/5] Billboard FAILED (check logs)"
    exit 1
fi

# Step 3: MusicBrainz enrichment
log "[3/5] Enriching with MusicBrainz (rate-limited, ~50s)..."
if python3 "$SCRIPT_DIR/musicbrainz_lookup.py" >> "$LOG_DIR/musicbrainz_$TODAY.log" 2>&1; then
    log "[3/5] MusicBrainz OK"
else
    log "[3/5] MusicBrainz FAILED (check logs)"
    exit 1
fi

# Step 4: AI analysis
log "[4/5] Running LLM analysis..."
if python3 "$SCRIPT_DIR/ai_analyze.py" >> "$LOG_DIR/ai_$TODAY.log" 2>&1; then
    log "[4/5] AI analysis OK"
else
    log "[4/5] AI analysis FAILED (check logs)"
    exit 1
fi

# Step 5: Music generation + S3 upload
log "[5/5] Generating music (MiniMax) + uploading to S3..."
if python3 "$SCRIPT_DIR/music_generate.py" >> "$LOG_DIR/music_generate_$TODAY.log" 2>&1; then
    log "[5/5] Music generation OK"
else
    log "[5/5] Music generation FAILED (check logs)"
    exit 1
fi

# Build manifest
MANIFEST_PATH="$MANIFEST_DIR/$TODAY.json"
if [[ -f "$MANIFEST_PATH" ]]; then
    COUNT=$(python3 -c "import json; d=json.load(open('$MANIFEST_PATH')); print(d.get('count', 0))")
    log "=== Pipeline complete: $COUNT tracks generated ==="
    log "Manifest: $MANIFEST_PATH"

    # Print summary
    python3 -c "
import json
d = json.load(open('$MANIFEST_PATH'))
print('Tracks:')
for t in d.get('tracks', []):
    print(f\"  [{t['index']}] mood={t['mood']} | {t['s3_url']}\")
"
else
    log "Manifest not found at $MANIFEST_PATH"
    exit 1
fi
