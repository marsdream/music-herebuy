#!/usr/bin/env python3
"""
music_generate.py — MiniMax music-2.6 generation + hi168 S3 upload
- Calls MiniMax music_generation API via subprocess+curl (avoids Python SSL issues)
- Downloads generated audio
- Uploads to hi168 S3 via presigned URL + httpx PUT
- Outputs manifest: ~/.openclaw/workspace/music-herebuy/data/manifest/YYYY-MM-DD.json
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date

import boto3
from botocore.config import Config
import httpx

IDEAS_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/ideas")
OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/manifest")
TOKEN_PATH = os.path.expanduser("~/.openclaw/credentials/minimax-portal_api_key.txt")
S3_CREDS_PATH = os.path.expanduser("~/.openclaw/credentials/hi168_s3.json")

MINIMAX_API = "https://api.minimax.chat/v1/music_generation"
MODEL = "music-2.6"
BUCKET = "hi168-hv6u2fnwrvs-jnilusqt-s"


def load_token():
    with open(TOKEN_PATH) as f:
        return f.read().strip()


def load_s3_creds():
    with open(S3_CREDS_PATH) as f:
        return json.load(f)


def load_ideas(date_str):
    path = os.path.join(IDEAS_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        print(f"[gen] ERROR: {path} not found. Run ai_analyze.py first.", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def generate_music_subprocess(token, prompt, timeout=480):
    """Call MiniMax music_generation via curl subprocess. Returns JSON response."""
    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "output_format": "url",
        "audio_setting": {
            "sample_rate": 44100,
            "bitrate": 256000,
            "format": "mp3",
        },
        "is_instrumental": True,
    })

    curl_cmd = [
        "curl", "-s", "--max-time", str(timeout),
        "-X", "POST",
        MINIMAX_API,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]

    print(f"[gen] Calling MiniMax music_generation (model={MODEL})...")
    result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        print(f"[gen] curl failed (rc={result.returncode}): {result.stderr[:500]}", file=sys.stderr)
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"[gen] Failed to parse response as JSON: {e}", file=sys.stderr)
        print(f"[gen] Raw response (first 500 chars): {result.stdout[:500]}", file=sys.stderr)
        return None


def poll_for_audio_url(data, token, timeout=480):
    """If initial response is async (status != 2), poll until ready."""
    status = data.get("data", {}).get("status")
    print(f"[gen] Initial status: {status}")

    if status == 2:
        return data

    # Poll
    task_id = data.get("data", {}).get("task_id") or data.get("data", {}).get("task_id")
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        print(f"[gen] API error: {base_resp.get('status_msg')}", file=sys.stderr)
        sys.exit(1)

    print(f"[gen] Polling for audio (task_id={task_id})...")
    start = time.time()
    poll_url = f"https://api.minimax.chat/v1/music_generation?task_id={task_id}"
    while time.time() - start < timeout:
        time.sleep(20)
        curl_cmd = [
            "curl", "-s", "--max-time", "30",
            poll_url,
            "-H", f"Authorization: Bearer {token}",
        ]
        r = subprocess.run(curl_cmd, capture_output=True, text=True)
        try:
            poll_data = json.loads(r.stdout)
            s = poll_data.get("data", {}).get("status")
            print(f"[gen]   poll status={s} ({int(time.time()-start)}s elapsed)")
            if s == 2:
                return poll_data
        except Exception:
            pass

    print("[gen] Timeout waiting for audio generation", file=sys.stderr)
    sys.exit(1)


def download_audio(url, timeout=120):
    """Download audio from URL using curl."""
    print(f"[gen] Downloading audio from {url[:80]}...")
    curl_cmd = [
        "curl", "-s", "--max-time", str(timeout),
        "-o", "/tmp/music_gen_audio.mp3",
        url,
    ]
    r = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=timeout + 10)
    if r.returncode != 0:
        print(f"[gen] Download failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    size = os.path.getsize("/tmp/music_gen_audio.mp3")
    print(f"[gen] Downloaded {size} bytes -> /tmp/music_gen_audio.mp3")
    return size


def get_presigned_url(creds, object_key):
    """Generate a presigned PUT URL for hi168 S3 using boto3."""
    s3 = boto3.client(
        's3',
        endpoint_url=creds["endpoint"],
        aws_access_key_id=creds["access_key_id"],
        aws_secret_access_key=creds["secret_access_key"],
        region_name=creds.get("region", "us-east-1"),
        config=Config(s3={'addressing_style': 'path'}, signature_version='s3v4')
    )
    presigned = s3.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': BUCKET,
            'Key': object_key,
            'ContentType': 'audio/mpeg',
        },
        ExpiresIn=86400,
    )
    return presigned


def upload_to_s3(presigned_url, file_path, content_type="audio/mpeg"):
    """Upload file to S3 via presigned URL using httpx PUT."""
    print(f"[gen] Uploading to S3 via presigned URL...")
    with open(file_path, "rb") as f:
        data = f.read()

    with httpx.Client(timeout=httpx.Timeout(120.0)) as client:
        resp = client.put(presigned_url, content=data, headers={"Content-Type": content_type})
        if resp.status_code not in (200, 204):
            print(f"[gen] S3 upload failed: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            sys.exit(1)
        print(f"[gen] S3 upload OK: {resp.status_code}")


def main():
    today = date.today().isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{today}.json")

    ideas = load_ideas(today)
    prompts = ideas.get("prompts", [])
    if not prompts:
        print("[gen] ERROR: No prompts found in ideas file", file=sys.stderr)
        sys.exit(1)

    print(f"[gen] Found {len(prompts)} prompts, generating music for each...")

    token = load_token()
    creds = load_s3_creds()

    generated = []
    for i, item in enumerate(prompts):
        idx = item.get("index", i + 1)
        prompt_text = item.get("prompt", "")
        mood = item.get("mood", "")
        style_hint = item.get("style_hint", "")

        print(f"\n[gen] [{idx}/{len(prompts)}] Generating: {prompt_text[:80]}...")
        try:
            raw = generate_music_subprocess(token, prompt_text)
            if raw is None:
                print("[gen] ERROR: empty response for track", idx, file=sys.stderr)
                continue
            data = poll_for_audio_url(raw, token)

            audio_url = data.get("data", {}).get("audio", "") or data.get("data", {}).get("audio_url", "")
            if not audio_url:
                print(f"[gen] ERROR: No audio in response: {json.dumps(data, indent=2)[:300]}", file=sys.stderr)
                continue

            size = download_audio(audio_url)
        except Exception as e:
            print(f"[gen] ERROR generating track {idx}: {e}", file=sys.stderr)
            continue

        # Upload to S3 — follow Sonic's naming convention: title.meta.json, title.mp3, title.歌词.txt
        title = item.get("title", f"track_{idx:02d}").replace("/", "_").replace("\\", "_")
        lyrics = item.get("lyrics", "")
        genre = item.get("genre", "")
        style_hint_text = item.get("style_hint", style_hint)
        duration_hint = item.get("duration", "约 30s")

        # MP3
        mp3_key = f"music/{today}/{title}.mp3"
        presigned_mp3 = get_presigned_url(creds, mp3_key)
        upload_to_s3(presigned_mp3, "/tmp/music_gen_audio.mp3")
        s3_url = f"{creds['endpoint'].rstrip('/')}/{BUCKET}/{mp3_key}"

        # meta.json
        meta = {
            "title": title,
            "genre": genre or "AI Generated",
            "style": style_hint_text,
            "bpm": item.get("bpm", 120),
            "date": today,
            "prompt": prompt_text,
            "provider": "minimax-portal/music-2.6",
            "format": "mp3, 256kbps, 44100Hz, stereo",
            "duration_real": duration_hint,
            "mood": mood,
        }
        with tempfile.NamedTemporaryFile("w", suffix=".meta.json", delete=False, encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
            meta_path = f.name
        presigned_meta = get_presigned_url(creds, f"music/{today}/{title}.meta.json")
        upload_to_s3(presigned_meta, meta_path, content_type="application/json")
        os.unlink(meta_path)

        # 歌词.txt
        if lyrics:
            lyrics_path = tempfile.mktemp(suffix=".歌词.txt")
            with open(lyrics_path, "w", encoding="utf-8") as f:
                f.write(lyrics)
            presigned_lyrics = get_presigned_url(creds, f"music/{today}/{title}.歌词.txt")
            upload_to_s3(presigned_lyrics, lyrics_path, content_type="text/plain")
            os.unlink(lyrics_path)

        idea_id = item.get("idea_id")  # set by ai_analyze.py after Supabase insert
        generated.append({
            "index": idx,
            "title": title,
            "prompt": prompt_text,
            "mood": mood,
            "style_hint": style_hint_text,
            "lyrics": lyrics,
            "source_url": audio_url,
            "s3_url": s3_url,
            "size_bytes": size,
            "idea_id": idea_id,
        })

    manifest = {
        "date": today,
        "model": MODEL,
        "count": len(generated),
        "tracks": generated,
    }

    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n[gen] Manifest written to {output_path}")

    # --- Write each generation to Supabase `music_generations` table (warning only on failure) ---
    try:
        from supabase_client import bulk_insert, resolve_user, resolve_agent
        user_id = resolve_user("marsdream")
        agent_id = resolve_agent("Yuki")
        gen_rows = []
        for g in generated:
            s3_url = g.get("s3_url") or ""
            gen_rows.append({
                "idea_id": g.get("idea_id"),
                "user_id": user_id,
                "agent_id": agent_id,
                "prompt_used": g.get("prompt", ""),
                "s3_mp3_url": s3_url,
                "s3_meta_url": s3_url.replace(".mp3", ".meta.json") if s3_url else None,
                "s3_lyrics_url": s3_url.replace(".mp3", ".歌词.txt") if s3_url else None,
                "provider": "minimax-portal/music-2.6",
                "status": "success",
            })
        if gen_rows and bulk_insert("music_generations", gen_rows):
            print(f"[gen] Supabase: inserted {len(gen_rows)} music_generations rows "
                  f"(user=marsdream, agent=Yuki)")
        elif gen_rows:
            print("[gen] Supabase: bulk insert failed (warning, local manifest unaffected)")
    except Exception as e:
        print(f"[gen] Supabase: skipped (init error: {e})", file=sys.stderr)

    return output_path


if __name__ == "__main__":
    main()
