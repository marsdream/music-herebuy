#!/usr/bin/env python3
"""
musicbrainz_lookup.py — Enrich Last.fm tracks with MusicBrainz data
Input:  lastfm JSON (MBID field)
Output: musicbrainz JSON with song name, artist, release_id + Spotify search URL
Rate limit: 1 req/sec (sleep 1 between calls)
User-Agent: MusicInspirationBot/1.0 (contact@marsdream.com)
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import date

LASTFM_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/lastfm")
OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/musicbrainz")
MB_API = "https://musicbrainz.org/ws/2/recording/"


def build_mb_url(mbid):
    params = urllib.parse.urlencode({
        "fmt": "json",
        "inc": "releases+artist-credits",
    })
    return f"{MB_API}{mbid}?{params}"


def lookup_recording(mbid):
    url = build_mb_url(mbid)
    headers = {
        "User-Agent": "MusicInspirationBot/1.0 (contact@marsdream.com)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def build_spotify_url(title, artist):
    q = urllib.parse.quote(f"{title} {artist}")
    return f"https://open.spotify.com/search/{q}"


def enrich_track(mbid):
    try:
        data = lookup_recording(mbid)
    except Exception as e:
        print(f"[mb] ERROR looking up {mbid}: {e}", file=sys.stderr)
        return None

    if "title" not in data:
        return None

    title = data["title"]
    artist_name = ""
    if "artist-credits" in data and data["artist-credits"]:
        artist_name = data["artist-credits"][0].get("name", "")

    release_id = ""
    releases = data.get("releases", [])
    if releases:
        release_id = releases[0].get("id", "")

    return {
        "mbid": mbid,
        "title": title,
        "artist": artist_name,
        "release_id": release_id,
        "spotify_url": build_spotify_url(title, artist_name),
    }


def main():
    today = date.today().isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{today}.json")

    # Load today's lastfm data
    lastfm_path = os.path.join(LASTFM_DIR, f"{today}.json")
    if not os.path.exists(lastfm_path):
        print(f"[mb] ERROR: {lastfm_path} not found. Run lastfm_fetch.py first.", file=sys.stderr)
        sys.exit(1)

    with open(lastfm_path) as f:
        lastfm_data = json.load(f)

    tracks = lastfm_data.get("tracks", [])
    print(f"[mb] Processing {len(tracks)} tracks from Last.fm")

    results = []
    for i, track in enumerate(tracks):
        mbid = track.get("mbid", "").strip()
        if not mbid:
            print(f"[mb] [{i+1}/{len(tracks)}] skip (no mbid): {track.get('title','')}")
            time.sleep(0.2)
            continue

        print(f"[mb] [{i+1}/{len(tracks)}] lookup mbid={mbid}")
        enriched = enrich_track(mbid)
        time.sleep(1)  # Rate limit: 1 req/sec

        if enriched:
            results.append(enriched)
            print(f"  -> {enriched['title']} / {enriched['artist']} / release={enriched['release_id']}")
        else:
            print(f"  -> FAILED")

    output = {"date": today, "count": len(results), "tracks": results}

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[mb] Wrote {len(results)} enriched tracks to {output_path}")

    # --- Update Supabase `charts` table with spotify_url (warning only on failure) ---
    try:
        from supabase_client import update_by_column
        # Match by (track_name, artist) on charts rows where source='lastfm'.
        # Supabase REST PATCH supports a single column =eq.value; to filter on
        # track_name + artist we write one row at a time using both columns
        # via a composite filter URL.
        import urllib.parse
        from supabase_client import _load_creds, _resolve_service_role_key
        creds = _load_creds()
        key = _resolve_service_role_key()
        base = creds["rest_api"]
        updated = 0
        for enriched in results:
            fn = urllib.parse.quote(enriched.get("title", ""))
            ar = urllib.parse.quote(enriched.get("artist", ""))
            url = (
                f"{base}/charts?"
                f"track_name=eq.{fn}&artist=eq.{ar}&source=eq.lastfm"
            )
            headers = {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            }
            body = json.dumps({"spotify_url": enriched.get("spotify_url")}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="PATCH")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    updated += 1
            except urllib.error.HTTPError as e:
                print(f"[mb] Supabase update warning ({e.code}): {e.read().decode()[:120]}",
                      file=sys.stderr)
        print(f"[mb] Supabase: updated {updated}/{len(results)} charts rows with spotify_url")
    except Exception as e:
        print(f"[mb] Supabase: skipped spotify_url update (init error: {e})", file=sys.stderr)

    return output_path


if __name__ == "__main__":
    main()
