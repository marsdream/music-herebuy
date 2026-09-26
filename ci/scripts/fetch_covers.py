#!/usr/bin/env python3
"""Fetch album covers and store as cover_url in Supabase.
- Last.fm tracks: upload to 1yunpan S3, store S3 URL as cover_url
- Billboard tracks: store iTunes artwork URL directly as cover_url
"""
import os, sys, json, time, re, urllib.parse, subprocess, datetime, hashlib, hmac, urllib.request

S3_ENDPOINT = 'https://s3.1yunpan.com'
S3_BUCKET = '5qsfmqsm5ukg'
PROJECT_REF = 'adfirxacvkcoasbujbgo'
SUPABASE_URL = f'https://{PROJECT_REF}.supabase.co'
DEFAULT_COVER_URL = 'https://img.osp.io/default_cover.png'
RATE_LIMIT_DELAY = 0.3


def s3_cred():
    ak = os.environ.get('S1YUNPAN_ACCESS_KEY_ID', '')
    sk = os.environ.get('S1YUNPAN_SECRET_ACCESS_KEY', '')
    return (ak, sk) if (ak and sk) else (None, None)


def sig_v4(ak, sk, method, path, host, extra_headers, body_hash):
    t = datetime.datetime.utcnow()
    amz_date = t.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = t.strftime('%Y%m%d')
    region = 'auto'
    service = 's3'
    headers = {**extra_headers, 'x-amz-date': amz_date}
    canonical = f'{method}\n{path}\n\n' + '\n'.join(f'{k}:{headers[k]}' for k in sorted(headers.keys())) + f'\n\n' + ';'.join(sorted(headers.keys())) + f'\n{body_hash}'
    canonical_hash = hashlib.sha256(canonical.encode()).hexdigest()
    scope = f'{date_stamp}/{region}/{service}/aws4_request'
    sts = f'AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{canonical_hash}'
    k1 = hmac.new(b'AWS4' + sk.encode(), date_stamp.encode(), hashlib.sha256).digest()
    k2 = hmac.new(k1, region.encode(), hashlib.sha256).digest()
    k3 = hmac.new(k2, service.encode(), hashlib.sha256).digest()
    k4 = hmac.new(k3, b'aws4_request', hashlib.sha256).digest()
    sig = hmac.new(k4, sts.encode(), hashlib.sha256).hexdigest()
    auth = f'AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders=' + ';'.join(sorted(headers.keys())) + f', Signature={sig}'
    return amz_date, auth


def upload_1yunpan(ak, sk, key, data):
    host = 's3.1yunpan.com'
    path = f'/{S3_BUCKET}/{key}'
    body_hash = hashlib.sha256(data).hexdigest()
    headers = {'content-type': 'image/jpeg', 'host': host, 'x-amz-content-sha256': body_hash}
    amz_date, auth = sig_v4(ak, sk, 'PUT', path, host, headers, body_hash)
    h = {**headers, 'x-amz-date': amz_date, 'Authorization': auth}
    with open('/tmp/_cover_up.jpg', 'wb') as f:
        f.write(data)
    r = subprocess.run([
        'curl', '-s', '-X', 'PUT', '--noproxy', '*', '-T', '/tmp/_cover_up.jpg',
    ] + sum([['-H', f'{k}: {v}'] for k, v in sorted(h.items())], []) + [
        f'{S3_ENDPOINT}/{S3_BUCKET}/{key}', '-w', '\nHTTP_CODE:%{http_code}'
    ], capture_output=True, text=True)
    return 'HTTP_CODE:200' in r.stdout


def get_chart_tracks(date, source):
    anon_key = os.environ.get('SUPABASE_ANON_KEY', '')
    url = f'{SUPABASE_URL}/rest/v1/charts?date=eq.{date}&source=eq.{source}&select=date,mbid,artist,track_name,rank'
    req = urllib.request.Request(url)
    req.add_header('apikey', anon_key)
    req.add_header('Authorization', 'Bearer ' + anon_key)
    req.add_header('Accept-Profile', 'public')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def update_cover_url(track, cover_url):
    """Update cover_url in Supabase charts table. Uses date+source+rank for unique match."""
    anon_key = os.environ.get('SUPABASE_ANON_KEY', '')
    # Use date+source+rank as unique key (mbid may be empty for Billboard)
    query = f"date=eq.{track['date']}&source=eq.{track['source']}&rank=eq.{track['rank']}"
    url = f'{SUPABASE_URL}/rest/v1/charts?{query}'
    payload = json.dumps({'cover_url': cover_url}).encode()
    req = urllib.request.Request(url, data=payload, method='PATCH')
    req.add_header('apikey', anon_key)
    req.add_header('Authorization', 'Bearer ' + anon_key)
    req.add_header('Content-Type', 'application/json')
    req.add_header('Prefer', 'return=minimal')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204, 201)
    except Exception as e:
        print(f'    DB update error: {e}')
        return False


def search_itunes(artist, track):
    q = urllib.parse.quote(f'{artist} {track}')
    for attempt in range(2):
        try:
            u = f'https://itunes.apple.com/search?term={q}&entity=song&limit=1'
            with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=8) as r:
                res = json.loads(r.read())
            if res.get('resultCount', 0) > 0:
                artwork = res['results'][0].get('artworkUrl600') or res['results'][0].get('artworkUrl100')
                if artwork:
                    return artwork.replace('600x600', '300x300')
        except Exception:
            pass
        time.sleep(0.5)
    return None


def download_image(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    except Exception:
        return None


def main():
    ak, sk = s3_cred()
    if not ak:
        print('Error: S1YUNPAN_ACCESS_KEY_ID / S1YUNPAN_SECRET_ACCESS_KEY not set')
        sys.exit(1)

    anon_key = os.environ.get('SUPABASE_ANON_KEY', '')
    url = f'{SUPABASE_URL}/rest/v1/charts?select=date&order=date.desc&limit=1'
    req = urllib.request.Request(url)
    req.add_header('apikey', anon_key)
    req.add_header('Authorization', 'Bearer ' + anon_key)
    req.add_header('Accept-Profile', 'public')
    with urllib.request.urlopen(req, timeout=10) as r:
        dates = json.loads(r.read())
    if not dates:
        print('No chart dates found')
        return
    latest_date = dates[0]['date']
    print(f'Processing date: {latest_date}')

    for source in ['lastfm', 'billboard']:
        tracks = get_chart_tracks(latest_date, source)
        print(f'  {source}: {len(tracks)} tracks')
        new_covers = skip_count = fail_count = 0

        for t in tracks:
            mbid = t.get('mbid') or ''
            track_name = t['track_name']
            artist = t['artist']
            rank = t['rank']

            artwork_url = search_itunes(artist, track_name)
            if not artwork_url:
                print(f'  [{rank}] {track_name} - {artist}: no iTunes match, using default')
                update_cover_url(t, DEFAULT_COVER_URL)
                new_covers += 1
                time.sleep(RATE_LIMIT_DELAY)
                continue

            if source == 'lastfm' and mbid:
                # Upload to 1yunpan, store S3 URL
                img_data = download_image(artwork_url)
                if img_data and upload_1yunpan(ak, sk, f'covers/{mbid}.jpg', img_data):
                    s3_url = f'https://id5qsfmqsm5ukg.1yunpan.com/covers/{mbid}.jpg'
                    update_cover_url(t, s3_url)
                    print(f'  [{rank}] {track_name} - {artist}: {len(img_data)} bytes -> 1yunpan')
                    new_covers += 1
                else:
                    # Fallback to iTunes URL directly
                    update_cover_url(t, artwork_url)
                    print(f'  [{rank}] {track_name} - {artist}: upload failed, using iTunes direct')
                    fail_count += 1
            else:
                # Billboard or no MBID: store iTunes URL directly as cover_url
                update_cover_url(t, artwork_url)
                print(f'  [{rank}] {track_name} - {artist}: iTunes direct -> {artwork_url[-40:]}')
                new_covers += 1

            time.sleep(RATE_LIMIT_DELAY)

        print(f'  {source}: {new_covers} new, {skip_count} skipped, {fail_count} failed')

    print('Done')


if __name__ == '__main__':
    main()
