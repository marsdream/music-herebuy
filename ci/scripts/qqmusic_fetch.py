#!/usr/bin/env python3
"""Fetch QQ Music Europe & US chart (topId=3) and store in Supabase."""
import os, sys, json, urllib.request, datetime

PROJECT_REF = 'adfirxacvkcoasbujbgo'
SUPABASE_URL = f'https://{PROJECT_REF}.supabase.co'
BASE_URL = 'https://a.y.qq.com'
CHART_ID = 3
SKILL_VERSION = '0.0.3'

def supabase_headers():
    anon_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_ANON_KEY', '')
    return {'apikey': anon_key, 'Authorization': f'Bearer {anon_key}', 'Content-Type': 'application/json', 'Accept-Profile': 'public'}

def call_qqmusic(path, params):
    api_key = os.environ.get('QQMUSIC_API_KEY', '')
    if not api_key:
        print('Error: QQMUSIC_API_KEY not set')
        sys.exit(1)
    body = json.dumps({'params': params, 'comm': {'skill_version': SKILL_VERSION}}).encode()
    req = urllib.request.Request(f'{BASE_URL}{path}', data=body, method='POST')
    req.add_header('Authorization', f'Bearer {api_key}')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def fetch_all_pages(top_id):
    all_tracks, page = [], 0
    while True:
        data = call_qqmusic('/charts/detail', {'topId': top_id, 'page': page})
        tracks = data.get('trackList', [])
        all_tracks.extend(tracks)
        if not data.get('hasMore'): break
        page += 1
        if page > 5: break
    return data.get('topName', ''), all_tracks

def today_date():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')

def upsert_track(date, source, rank, song_mid, song_name, singer_name, cover_url):
    anon_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_ANON_KEY', '')
    query = f'date=eq.{date}&source=eq.{source}&rank=eq.{rank}'
    url = f'{SUPABASE_URL}/rest/v1/charts?{query}'
    req = urllib.request.Request(url)
    for k, v in supabase_headers().items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            existing = json.loads(resp.read())
    except Exception as e:
        print(f'  Query error: {e}'); return False
    payload = {'date': date, 'source': source, 'rank': rank, 'mbid': song_mid, 'track_name': song_name, 'artist': singer_name, 'cover_url': cover_url}
    if existing:
        req2 = urllib.request.Request(url, data=json.dumps(payload).encode(), method='PATCH')
        for k, v in supabase_headers().items(): req2.add_header(k, v)
        req2.add_header('Prefer', 'return=minimal')
        try:
            with urllib.request.urlopen(req2, timeout=10) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            print(f'  Update error: {e}'); return False
    else:
        req3 = urllib.request.Request(f'{SUPABASE_URL}/rest/v1/charts', data=json.dumps(payload).encode(), method='POST')
        for k, v in supabase_headers().items(): req3.add_header(k, v)
        req3.add_header('Prefer', 'return=minimal')
        try:
            with urllib.request.urlopen(req3, timeout=10) as resp:
                return resp.status in (200, 201)
        except Exception as e:
            print(f'  Insert error: {e}'); return False

def main():
    date = today_date()
    print(f'Fetching QQ Music Europe & US chart for {date}...')
    top_name, tracks = fetch_all_pages(CHART_ID)
    print(f'  Chart: {top_name}, Tracks: {len(tracks)}')
    success = 0
    for i, t in enumerate(tracks):
        rank = i + 1
        song_mid = t.get('songMid', '')
        song_name = t.get('songName', '')
        singer_name = t.get('singerName', '')
        cover_url = t.get('albumImageUrl', '') or ''
        if not song_name: continue
        ok = upsert_track(date, 'qqmusic', rank, song_mid, song_name, singer_name, cover_url)
        label = f'  [{rank:3}] {song_name} -- {singer_name}'
        print(label if ok else label + ' FAILED')
        if ok: success += 1
    print(f'Done: {success}/{len(tracks)} tracks written')

if __name__ == '__main__': main()
