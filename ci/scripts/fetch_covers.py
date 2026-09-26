#!/usr/bin/env python3
"""Fetch album covers and upload to Cloudflare R2 (img.osp.io).
Skips tracks already having covers in R2. Falls back to default cover.
"""
import os, sys, json, time, re, urllib.parse
import boto3
from botocore.config import Config
import urllib.request

# R2 config
R2_ENDPOINT = 'https://95c11acbf13b01b3cd1ec169081835e1.r2.cloudflarestorage.com'
R2_BUCKET = 'imgbed'

# Supabase config
PROJECT_REF = 'adfirxacvkcoasbujbgo'
DEFAULT_COVER_URL = 'https://img.osp.io/default_cover.png'
RATE_LIMIT_DELAY = 0.3

if os.environ.get('R2_ACCESS_KEY_ID') and os.environ.get('R2_SECRET_ACCESS_KEY'):
    s3 = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto',
        config=Config(signature_version='s3v4')
    )
else:
    s3 = None
    print('Error: R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY not set')
    sys.exit(1)


def list_existing_covers():
    """Return set of cover keys already in R2."""
    resp = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix='covers/', MaxKeys=1000)
    return {obj['Key'] for obj in resp.get('Contents', [])}


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
            if res['resultCount'] > 0:
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


def upload_cover(key, data):
    for attempt in range(2):
        try:
            s3.put_object(Bucket=R2_BUCKET, Key=key, Body=data, ContentType='image/jpeg')
            return True
        except Exception as e:
            print(f'    Upload error (attempt {attempt+1}): {e}')
            time.sleep(1)
    return False


def safe_key(mbid, artist, track):
    if mbid:
        return f'covers/{mbid}.jpg'
    # fallback: safe filename from artist+track
    safe = re.sub(r'[^\w\-_ ]', '_', f'{artist} {track}')[:80]
    return f'covers/{safe}.jpg'


def main():
    existing = list_existing_covers()
    print(f'Existing covers in R2: {len(existing)}')

    anon_key = os.environ.get('SUPABASE_ANON_KEY', '')
    # Get latest chart date
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
                if img_data and upload_cover(key, img_data):
                    print(f'  [{t["rank"]}] {t["artist"]} - {t["track_name"]} -> uploaded')
                    new_covers += 1
                else:
                    fail_count += 1
            else:
                # Fallback to default cover
                img_data = download_image(DEFAULT_COVER_URL)
                if img_data:
                    upload_cover(key, img_data)
                    print(f'  [{t["rank"]}] {t["artist"]} - {t["track_name"]} -> default (no iTunes match)')
                new_covers += 1

            existing.add(key)
            time.sleep(RATE_LIMIT_DELAY)

        print(f'  {source}: {new_covers} new, {skip_count} skipped, {fail_count} failed')

    print('Done')


if __name__ == '__main__':
    main()
