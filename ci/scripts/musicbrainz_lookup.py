#!/usr/bin/env python3
"""
musicbrainz_lookup.py — Enrich Last.fm + Billboard tracks with MusicBrainz + Spotify URLs
Input:  lastfm JSON (has mbid) + billboard JSON (no mbid)
Output: Spotify search URL for every track
Logic:
  - Has mbid (Last.fm): query MusicBrainz API for canonical title/artist
  - No mbid (Billboard): build Spotify search URL directly from track_name + artist
Rate limit: 1 req/sec for MB API calls only
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

LASTFM_DIR   = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/lastfm")
BILLBOARD_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/billboard")
OUTPUT_DIR   = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/musicbrainz")
MB_API       = "https://musicbrainz.org/ws/2/recording/"


def build_spotify_url(title, artist):
    q = urllib.parse.quote(f"{title} {artist}")
    return f"https://open.spotify.com/search/{q}"


def lookup_recording(mbid):
    params = urllib.parse.urlencode({"fmt": "json", "inc": "releases+artist-credits"})
    url = f"{MB_API}{mbid}?{params}"
    headers = {
        "User-Agent": "MusicInspirationBot/1.0 (contact@marsdream.com)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def enrich_by_mbid(mbid, title, artist):
    """Query MB for canonical title/artist, return enriched dict or None."""
    try:
        data = lookup_recording(mbid)
    except Exception as e:
        print(f"[mb] ERROR {mbid}: {e}", file=sys.stderr)
        return None
    if "title" not in data:
        return None
    mb_title = data["title"]
    mb_artist = ""
    if data.get("artist-credits"):
        mb_artist = data["artist-credits"][0].get("name", "")
    return {
        "mbid": mbid,
        "track_name": mb_title,
        "artist": mb_artist,
        "source": "lastfm",
        "spotify_url": build_spotify_url(mb_title, mb_artist),
    }


def enrich_direct(title, artist, source):
    """Build Spotify search URL directly (no MB lookup needed)."""
    return {
        "track_name": title,
        "artist": artist,
        "source": source,
        "spotify_url": build_spotify_url(title, artist),
    }


def update_supabase_spotify(rows):
    """PATCH spotify_url for all rows in Supabase charts table, matched by track_name+artist+source."""
    try:
        from supabase_client import _load_creds, _resolve_service_role_key
        import urllib.parse
        creds = _load_creds()
        key = _resolve_service_role_key()
        base = creds["rest_api"]
        updated = 0
        for row in rows:
            fn = urllib.parse.quote(row.get("track_name", ""))
            ar = urllib.parse.quote(row.get("artist", ""))
            src = row.get("source", "")
            sp_url = row.get("spotify_url", "")
            if not fn or not ar:
                continue
            url = f"{base}/charts?track_name=eq.{fn}&artist=eq.{ar}&source=eq.{src}"
            headers = {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            }
            body = json.dumps({"spotify_url": sp_url}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="PATCH")
            try:
                with urllib.request.urlopen(req, timeout=15):
                    updated += 1
            except urllib.error.HTTPError as e:
                print(f"[mb] PATCH warning {row.get('track_name','')}: {e.code}", file=sys.stderr)
        print(f"[mb] Supabase: updated {updated}/{len(rows)} rows with spotify_url")
    except Exception as e:
        print(f"[mb] Supabase update skipped: {e}", file=sys.stderr)


def main():
    today = date.today().isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load Last.fm tracks (have mbid)
    lastfm_path = os.path.join(LASTFM_DIR, f"{today}.json")
    lastfm_tracks = []
    if os.path.exists(lastfm_path):
        with open(lastfm_path) as f:
            data = json.load(f)
            lastfm_tracks = data.get("tracks", [])
        print(f"[mb] Loaded {len(lastfm_tracks)} Last.fm tracks")
    else:
        print(f"[mb] WARNING: {lastfm_path} not found")

    # Load Billboard tracks (no mbid)
    billboard_path = os.path.join(BILLBOARD_DIR, f"{today}.json")
    billboard_tracks = []
    if os.path.exists(billboard_path):
        with open(billboard_path) as f:
            data = json.load(f)
            # Billboard JSON: {"date": "...", "data": [...]} or {"tracks": [...]}
            billboard_tracks = data.get("data", data.get("tracks", []))
        print(f"[mb] Loaded {len(billboard_tracks)} Billboard tracks")
    else:
        print(f"[mb] WARNING: {billboard_path} not found")

    all_tracks = lastfm_tracks + billboard_tracks
    print(f"[mb] Processing {len(all_tracks)} total tracks")

    results = []
    total = len(all_tracks)

    for i, track in enumerate(all_tracks):
        title  = track.get("title",  track.get("song",  ""))
        artist = track.get("artist", "")
        mbid   = track.get("mbid",   "").strip()
        source = "lastfm" if i < len(lastfm_tracks) else "billboard"

        if mbid:
            print(f"[mb] [{i+1}/{total}] MB lookup {mbid}: {title}")
            enriched = enrich_by_mbid(mbid, title, artist)
            time.sleep(1)  # MB rate limit: 1 req/sec
            if enriched:
                results.append(enriched)
                print(f"  -> {enriched['track_name']} / {enriched['artist']}")
            else:
                # MB failed, fall back to direct
                results.append(enrich_direct(title, artist, source))
        else:
            # No mbid (Billboard): build Spotify URL directly
            print(f"[mb] [{i+1}/{total}] direct: {title} / {artist}")
            results.append(enrich_direct(title, artist, source))

    # Write enriched data
    output = {"date": today, "count": len(results), "tracks": results}
    output_path = os.path.join(OUTPUT_DIR, f"{today}.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"[mb] Wrote {len(results)} enriched tracks to {output_path}")

    # Update Supabase
    update_supabase_spotify(results)


if __name__ == "__main__":
    main()

