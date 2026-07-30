#!/usr/bin/env python3
"""
billboard_fetch.py — Fetch Billboard Hot 100 from GitHub repo
GitHub API: https://api.github.com/repos/mhollingshead/billboard-hot-100/contents/recent.json
Decodes base64 content.
Outputs: ~/.openclaw/workspace/music-herebuy/data/billboard/YYYY-MM-DD.json
Fields: song, artist, this_week, last_week, peak_position, weeks_on_chart
"""

import base64
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

    # --- Write to Supabase `charts` table (warning only on failure) ---
    try:
        from supabase_client import bulk_insert, delete_where
        today_iso = today
        rows = [
            {
                "date": today_iso,
                "source": "billboard",
                "track_name": entry.get("song", ""),
                "artist": entry.get("artist", ""),
                "rank": int(entry.get("this_week", 0)),
                "spotify_url": None,
            }
            for entry in entries
        ]
        if rows:
            # Delete stale data for this date+source before inserting fresh batch
            delete_where("charts", {"date": today_iso, "source": "billboard"})
            if bulk_insert("charts", rows):
                print(f"[billboard] Supabase: inserted {len(rows)} charts rows (source=billboard)")
            else:
                print("[billboard] Supabase: bulk insert failed (warning, local JSON unaffected)")
    except Exception as e:
        print(f"[billboard] Supabase: skipped (init error: {e})", file=sys.stderr)

    return output_path


if __name__ == "__main__":
    main()
