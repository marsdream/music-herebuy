#!/usr/bin/env python3
"""
lastfm_fetch.py — Fetch Last.fm chart.getTopTracks (limit=50)
Outputs: ~/.openclaw/workspace/music-herebuy/data/lastfm/YYYY-MM-DD.json
Fields: title, artist, playcount, mbid
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import date

CREDENTIALS_PATH = os.path.expanduser("~/.openclaw/credentials/lastfm.json")
OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/lastfm")


def load_credentials():
    with open(CREDENTIALS_PATH) as f:
        return json.load(f)


def fetch_top_tracks(api_key):
    params = urllib.parse.urlencode({
        "method": "chart.getTopTracks",
        "limit": 50,
        "api_key": api_key,
        "format": "json",
    })
    url = f"https://ws.audioscrobbler.com/2.0/?{params}"
    print(f"[lastfm] Fetching: {url}")

    req = urllib.request.Request(url, headers={"User-Agent": "MusicInspirationBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    tracks = data.get("tracks", {}).get("track", [])
    results = []
    for t in tracks:
        results.append({
            "title": t.get("name", ""),
            "artist": t.get("artist", {}).get("name", ""),
            "playcount": int(t.get("playcount", 0)),
            "mbid": t.get("mbid", ""),
        })
    return results


def main():
    today = date.today().isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{today}.json")

    creds = load_credentials()
    api_key = creds.get("api_key")
    if not api_key:
        print("[lastfm] ERROR: No api_key in credentials file", file=sys.stderr)
        sys.exit(1)

    tracks = fetch_top_tracks(api_key)
    output = {"date": today, "count": len(tracks), "tracks": tracks}

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[lastfm] Wrote {len(tracks)} tracks to {output_path}")
    print(f"[lastfm] Output: {output_path}")

    # --- Write to Supabase `charts` table (warning only on failure) ---
    try:
        from supabase_client import bulk_insert, delete_where
        today_iso = today  # e.g. "2026-07-30"
        rows = [
            {
                "date": today_iso,
                "source": "lastfm",
                "track_name": t.get("title", ""),
                "artist": t.get("artist", ""),
                "rank": i + 1,
                "playcount": t.get("playcount", 0),
                "mbid": t.get("mbid", "") or None,
                "spotify_url": None,
            }
            for i, t in enumerate(tracks)
        ]
        if rows:
            # Delete stale data for this date+source before inserting fresh batch
            delete_where("charts", {"date": today_iso, "source": "lastfm"})
            if bulk_insert("charts", rows):
                print(f"[lastfm] Supabase: inserted {len(rows)} charts rows (source=lastfm)")
            else:
                print("[lastfm] Supabase: bulk insert failed (warning, local JSON unaffected)")
    except Exception as e:
        print(f"[lastfm] Supabase: skipped (init error: {e})", file=sys.stderr)

    return output_path


if __name__ == "__main__":
    main()
