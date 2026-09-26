#!/usr/bin/env python3
"""Fetch album covers and upload to 1yunpan S3 via curl (avoids boto3 chunked encoding bug).
Skips tracks already having covers. Falls back to default cover (img.osp.io).
"""
import os, sys, json, time, re, urllib.parse, subprocess, datetime, hashlib, hmac, urllib.request

S3_ENDPOINT = 'https://s3.1yunpan.com'
S3_BUCKET = '5qsfmqsm5ukg'
PROJECT_REF = 'adfirxacvkcoasbujbgo'
DEFAULT_COVER_URL = 'https://img.osp.io/default_cover.png'
RATE_LIMIT_DELAY = 0.3


def s3_cred():
    ak = os.environ.get('S1YUNPAN_ACCESS_KEY_ID', '')
    sk = os.environ.get('S1YUNPAN_SECRET_ACCESS_KEY', '')
    if not ak or not sk:
        return None, None
    return ak, sk


def sig_v4(ak, sk, method, path, host, headers, body_hash):
    t = datetime.datetime.utcnow()
    amz_date = t.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = t.strftime('%Y%m%d')
    region = 'auto'
    service = 's3'

    signed_headers = ';'.join(sorted(headers.keys()))
    canonical = f'{method}\n{path}\n\n' + '\n'.join(f'{k}:{v}' for k, v in sorted(headers.items())) + f'\n\n{signed_headers}\n{body_hash}'
    canonical_hash = hashlib.sha256(canonical.encode()).hexdigest()
    scope = f'{date_stamp}/{region}/{service}/aws4_request'
    sts = f'AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{canonical_hash}'

    k1 = hmac.new(b'AWS4' + sk.encode(), date_stamp.encode(), hashlib.sha256).digest()
    k2 = hmac.new(k1, region.encode(), hashlib.sha256).digest()
    k3 = hmac.new(k2, service.encode(), hashlib.sha256).digest()
    k4 = hmac.new(k3, b'aws4_request', hashlib.sha256).digest()
    sig = hmac.new(k4, sts.encode(), hashlib.sha256).hexdigest()
    auth = f'AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed_headers}, Signature={sig}'
    return amz_date, auth


def upload_curl(ak, sk, key, data):
    host = 's3.1yunpan.com'
    path = f'/{S3_BUCKET}/{key}'
    body_hash = hashlib.sha256(data).hexdigest()
    headers = {
        'content-type': 'image/jpeg',
        'host': host,
        'x-amz-content-sha256': body_hash,
    }
    amz_date, auth = sig_v4(ak, sk, 'PUT', path, host, headers, body_hash)
    headers['x-amz-date'] = amz_date
    headers['Authorization'] = auth

    with open('/tmp/_cover_upload.jpg', 'wb') as f:
        f.write(data)

    header_args = []
    for k, v in sorted(headers.items()):
        header_args += ['-H', f'{k}: {v}']

    r = subprocess.run([
        'curl', '-s', '-X', 'PUT',
        '--noproxy', '*',
        '-T', '/tmp/_cover_upload.jpg',
    ] + header_args + [
        f'{S3_ENDPOINT}/{S3_BUCKET}/{key}',
        '-w', '\nHTTP_CODE:%{http_code}'
    ], capture_output=True, text=True)
    return 'HTTP_CODE:200' in r.stdout


def list_existing():
    ak, sk = s3_cred()
    if not ak:
        return set()
    host = 's3.1yunpan.com'
    path = f'/{S3_BUCKET}/?list-type=2&prefix=covers/'
    body_hash = hashlib.sha256(b'').hexdigest()
    headers = {'host': host, 'x-amz-content-sha256': body_hash}
    amz_date, auth = sig_v4(ak, sk, 'GET', path, host, headers, body_hash)
    h = {'host': host, 'x-amz-content-sha256': body_hash, 'x-amz-date': amz_date, 'Authorization': auth}

    r = subprocess.run([
        'curl', '-s', '--noproxy', '*',
    ] + sum([['-H', f'{k}: {v}'] for k, v in sorted(h.items())], []) + [
        f'{S3_ENDPOINT}/{S3_BUCKET}/?list-type=2&prefix=covers/'
    ], capture_output=True, text=True)

    keys = re.findall(r'<Key>(covers/[^<]+)</Key>', r.stdout)
    return set(keys)


def get_chart_tracks(date, source):
    anon_key = os.environ.get('SUPABASE_ANON_KEY', '')
    url = f'https://{PROJECT_REF}.supabase.co/rest/v1/charts?date=eq.{date}&source=eq.{source}&select=mbid,artist,track_name,rank'
    req = urllib.request.Request(url)
    req.add_header('apikey', anon_key)
    req.add_header('Authorization', 'Bearer ' + anon_key)
    req.add_header('Accept-Profile', 'public')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


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


def safe_key(mbid, artist, track):
    if mbid:
        return f'covers/{mbid}.jpg'
    safe = re.sub(r'[^\w\-_ ]', '_', f'{artist} {track}')[:80]
    return f'covers/{safe}.jpg'


def main():
    ak, sk = s3_cred()
    if not ak:
        print('Error: S1YUNPAN_ACCESS_KEY_ID / S1YUNPAN_SECRET_ACCESS_KEY not set')
        sys.exit(1)

    existing = list_existing()
    print(f'Existing covers in 1yunpan: {len(existing)}')

    anon_key = os.environ.get('SUPABASE_ANON_KEY', '')
    url = f'https://{PROJECT_REF}.supabase.co/rest/v1/charts?select=date&order=date.desc&limit=1'
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
            key = safe_key(mbid, t['artist'], t['track_name'])

            if key in existing:
                skip_count += 1
                continue

            artwork_url = search_itunes(t['artist'], t['track_name'])
            if artwork_url:
                img_data = download_image(artwork_url)
                if img_data and upload_curl(ak, sk, key, img_data):
                    print(f'  [{t["rank"]}] {t["artist"]} - {t["track_name"]} -> ok ({len(img_data)} bytes)')
                    new_covers += 1
                else:
                    fail_count += 1
            else:
                img_data = download_image(DEFAULT_COVER_URL)
                if img_data:
                    upload_curl(ak, sk, key, img_data)
                    print(f'  [{t["rank"]}] {t["artist"]} - {t["track_name"]} -> default (no iTunes match)')
                new_covers += 1

            existing.add(key)
            time.sleep(RATE_LIMIT_DELAY)

        print(f'  {source}: {new_covers} new, {skip_count} skipped, {fail_count} failed')

    print('Done')


if __name__ == '__main__':
    main()
