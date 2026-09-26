#!/usr/bin/env python3
"""Fetch album covers and upload to 1yunpan S3.
Skips tracks already having covers. Falls back to default cover.
"""
import os, sys, json, time
import boto3
from botocore.config import Config
import urllib.request

# S3 config
S3_ENDPOINT = 'https://s3.1yunpan.com'
S3_BUCKET = '5qsfmqsm5ukg'
S3_KEY_ID = os.environ.get('S1YUNPAN_ACCESS_KEY_ID', '')
S3_KEY_SECRET = os.environ.get('S1YUNPAN_SECRET_ACCESS_KEY', '')

# Supabase config
ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', '')
PROJECT_REF = 'adfirxacvkcoasbujbgo'

# Minimal transparent PNG fallback (1x1 pixel)
DEFAULT_COVER_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00'
    b'\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx'
    b'\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)
DEFAULT_COVER_KEY = 'covers/default.png'

if S3_KEY_ID and S3_KEY_SECRET:
    s3 = boto3.client(
        's3', endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_KEY_ID,
        aws_secret_access_key=S3_KEY_SECRET,
        region_name='auto',
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'})
    )
else:
    # fallback for local dev
    s3 = None
    print('Warning: S3 credentials not set, dry run mode')


def get_existing_mbids():
    """Return set of MBIDs that already have covers in S3."""
    if not s3:
        return set()
    existing = set()
    try:
        resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix='covers/', MaxKeys=1000)
        for obj in resp.get('Contents', []):
            key = obj['Key']
            if key.startswith('covers/') and key.endswith('.jpg'):
                mbid = key[7:-4]
                existing.add(mbid)
    except Exception as e:
        print('Warning: could not list existing covers:', e)
    return existing


def ensure_default_cover():
    """Upload default cover if not already in S3."""
    if not s3:
        return
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=DEFAULT_COVER_KEY)
        print('  Default cover already exists')
    except Exception:
        s3.put_object(Bucket=S3_BUCKET, Key=DEFAULT_COVER_KEY,
                      Body=DEFAULT_COVER_PNG, ContentType='image/png')
        print('  Uploaded default cover')


def get_chart_tracks(date, source):
    url = f'https://{PROJECT_REF}.supabase.co/rest/v1/charts?date=eq.{date}&source=eq.{source}&select=mbid,artist,track_name,rank'
    req = urllib.request.Request(url)
    req.add_header('apikey', ANON_KEY)
    req.add_header('Authorization', 'Bearer ' + ANON_KEY)
    req.add_header('Accept-Profile', 'public')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def fetch_cover_itunes(artist, track, retries=2):
    q = (artist + ' ' + track).replace(' ', '+')
    for _ in range(retries):
        try:
            u = 'https://itunes.apple.com/search?term=' + q + '&entity=song&limit=1'
            with urllib.request.urlopen(u, timeout=8) as r:
                res = json.loads(r.read())
            if res['resultCount'] > 0:
                img = res['results'][0]['artworkUrl100'].replace('100x100', '600x600')
                with urllib.request.urlopen(img, timeout=8) as r:
                    return r.read(), r.headers.get('Content-Type', 'image/jpeg')
        except Exception:
            pass
        time.sleep(0.5)
    return None, None


def main():
    if not S3_KEY_ID or not S3_KEY_SECRET or not s3:
        print('Error: S1YUNPAN_ACCESS_KEY_ID / S1YUNPAN_SECRET_ACCESS_KEY / SUPABASE_ANON_KEY not set')
        sys.exit(1)

    ensure_default_cover()

    existing = get_existing_mbids()
    print('Existing covers in S3: ' + str(len(existing)))

    # Get latest chart date
    today_url = 'https://' + PROJECT_REF + '.supabase.co/rest/v1/charts?select=date&order=date.desc&limit=1'
    req = urllib.request.Request(today_url)
    req.add_header('apikey', ANON_KEY)
    req.add_header('Authorization', 'Bearer ' + ANON_KEY)
    req.add_header('Accept-Profile', 'public')
    with urllib.request.urlopen(req, timeout=10) as r:
        dates = json.loads(r.read())

    if not dates:
        print('No chart dates found')
        return

    latest_date = dates[0]['date']
    print('Processing date: ' + latest_date)

    for source in ['lastfm', 'billboard']:
        tracks = get_chart_tracks(latest_date, source)
        print('  ' + source + ': ' + str(len(tracks)) + ' tracks')
        new_count = skip_count = fail_count = 0

        for t in tracks:
            mbid = t.get('mbid')
            if not mbid or mbid in existing:
                skip_count += 1
                continue

            print('  Fetching: ' + t['artist'] + ' - ' + t['track_name'] + ' (mbid=' + mbid + ')')
            data, ctype = fetch_cover_itunes(t['artist'], t['track_name'])

            if data:
                key = 'covers/' + mbid + '.jpg'
                s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=ctype)
                print('    -> Uploaded ' + str(len(data)) + 'b')
                existing.add(mbid)
                new_count += 1
            else:
                # Use default cover as fallback
                try:
                    s3.copy_object(Bucket=S3_BUCKET, Key='covers/' + mbid + '.jpg',
                                   CopySource={'Bucket': S3_BUCKET, 'Key': DEFAULT_COVER_KEY})
                    print('    -> Used default cover (no art found)')
                    existing.add(mbid)
                except Exception as e:
                    print('    -> Default cover failed: ' + str(e))
                fail_count += 1
                new_count += 1

            time.sleep(0.3)

        print('  ' + source + ': ' + str(new_count) + ' new, ' + str(skip_count) + ' skipped, ' + str(fail_count) + ' failed')

    print('Done')


if __name__ == '__main__':
    main()
