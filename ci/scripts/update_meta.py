#!/usr/bin/env python3
"""Write last_updated timestamp to Supabase meta table."""
import os, urllib.request, json, datetime

PROJECT_REF = 'adfirxacvkcoasbujbgo'
SUPABASE_URL = f'https://{PROJECT_REF}.supabase.co'

def main():
    # Get current Shanghai time
    shanghai_tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(shanghai_tz)
    # Format: "Thu Sep 26 22:48:59 CST 2026"
    ts = now.strftime('%a %b %d %H:%M:%S CST %Y')

    anon_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if not anon_key:
        print('Error: SUPABASE_SERVICE_ROLE_KEY not set')
        return

    url = f'{SUPABASE_URL}/rest/v1/meta?key=eq.last_updated'
    req = urllib.request.Request(url)
    req.add_header('apikey', anon_key)
    req.add_header('Authorization', f'Bearer {anon_key}')
    req.add_header('Accept-Profile', 'public')

    payload = json.dumps({'value': ts}).encode()
    req2 = urllib.request.Request(url, data=payload, method='PATCH')
    req2.add_header('apikey', anon_key)
    req2.add_header('Authorization', f'Bearer {anon_key}')
    req2.add_header('Content-Type', 'application/json')
    req2.add_header('Prefer', 'return=minimal')

    try:
        with urllib.request.urlopen(req2, timeout=10) as resp:
            print(f'Updated last_updated: {ts}')
    except Exception as e:
        print(f'Error: {e}')

if __name__ == '__main__':
    main()
