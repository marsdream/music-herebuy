#!/usr/bin/env python3
"""
billboard_fetch.py — Fetch Billboard Hot 100 from GitHub repo
GitHub API: https://api.github.com/repos/mhollingshead/billboard-hot-100/contents/recent.json
Decodes base64 content.
Outputs: ~/.openclaw/workspace/music-herebuy/data/billboard/YYYY-MM-DD.json
Fields: song, artist, this_week, last_week, peak_position, weeks_on_chart
"""

import base64
import urllib.parse
import urllib.parse
import json
import os
import sys
import urllib.request
from datetime import date

OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/billboard")
GITHUB_API = "https://api.github.com/repos/mhollingshead/billboard-hot-100/contents/recent.json"


def fetch_billboard():
    print(f"[billboard] Fetching: {GITHUB_API}")
    req = urllib.request.Request(
        GITHUB_API,
        headers={"User-Agent": "MusicInspirationBot/1.0", "Accept": "application/vnd.github.v3+json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    content_b64 = data.get("content", "")
    # Remove newlines in base64 string
    content_b64_clean = content_b64.replace("\n", "")
    decoded = base64.b64decode(content_b64_clean).decode("utf-8")
    return json.loads(decoded)


def main():
    today = date.today().isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{today}.json")

    raw = fetch_billboard()

    # raw is a dict with a "data" or list under "data" key depending on repo structure
    # Let's inspect and handle flexibly
    entries = raw if isinstance(raw, list) else raw.get("data", raw.get("chart", []))
    if not isinstance(entries, list):
        print(f"[billboard] WARNING: unexpected data structure type={type(entries)}", file=sys.stderr)
        entries = []

    results = []
    for item in entries:
        results.append({
            "song": item.get("song", ""),
            "artist": item.get("artist", ""),
            "this_week": item.get("this_week", 0),
            "last_week": item.get("last_week", 0),
            "peak_position": item.get("peak_position", 0),
            "weeks_on_chart": item.get("weeks_on_chart", 0),
        })

    output = {"date": today, "count": len(results), "chart": results}

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[billboard] Wrote {len(results)} entries to {output_path}")

    # --- Write to Supabase `charts` table (upsert by date+source+rank) ---
    try:
        from supabase_client import upsert
        today_iso = today
        rows = []
        for entry in entries:
            title = entry.get("song", "")
            artist = entry.get("artist", "")
            sp_q = urllib.parse.quote(f"{title} {artist}")
            rows.append({
                "date": today_iso,
                "source": "billboard",
                "track_name": title,
                "artist": artist,
                "rank": int(entry.get("this_week", 0)),
                "spotify_url": f"https://open.spotify.com/search/{sp_q}",
            })
        # Upsert one-by-one using date+source+rank as conflict key
        succeeded = 0
        for row in rows:
            if upsert("charts", "date,source,rank", row):
                succeeded += 1
        print(f"[billboard] Supabase: upserted {succeeded}/{len(rows)} rows (source=billboard)")
    except Exception as e:
        print(f"[billboard] Supabase: skipped (init error: {e})", file=sys.stderr)

    return output_path


if __name__ == "__main__":
    main()
