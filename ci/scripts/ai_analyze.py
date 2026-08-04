#!/usr/bin/env python3
"""
ai_analyze.py — Analyze trending music data with LLM
Reads today's lastfm + billboard data, calls GLM-4 Flash via Zhipu AI,
outputs 3-5 music idea prompts.
Output: ~/.openclaw/workspace/music-herebuy/data/ideas/YYYY-MM-DD.json
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import date

LASTFM_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/lastfm")
BILLBOARD_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/billboard")
OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/music-herebuy/data/ideas")
GLM_API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_MODEL = "glm-4-flash"


def load_data(date_str):
    lastfm_path = os.path.join(LASTFM_DIR, f"{date_str}.json")
    billboard_path = os.path.join(BILLBOARD_DIR, f"{date_str}.json")

    lastfm_tracks = []
    if os.path.exists(lastfm_path):
        with open(lastfm_path) as f:
            d = json.load(f)
            lastfm_tracks = d.get("tracks", [])[:20]

    billboard_chart = []
    if os.path.exists(billboard_path):
        with open(billboard_path) as f:
            d = json.load(f)
            billboard_chart = d.get("chart", [])[:20]

    return lastfm_tracks, billboard_chart


def build_prompt(lastfm_tracks, billboard_chart):
    lastfm_sample = "\n".join(
        f"- {t['title']} / {t['artist']} (plays: {t['playcount']})"
        for t in lastfm_tracks[:15]
    )
    billboard_sample = "\n".join(
        f"- #{e['this_week']} {e['song']} / {e['artist']} (peak: #{e['peak_position']})"
        for e in billboard_chart[:15]
    )

    prompt = f"""You are a music trend analyst. Analyze today's trending music data and derive creative AI music generation prompts.

## Last.fm Global Top Tracks (by playcount)
{lastfm_sample}

## Billboard Hot 100 (this week)
{billboard_sample}

## Your Task
1. Identify 2-3 dominant emotional themes or moods (e.g., nostalgia, heartbreak, euphoria, late-night introspection)
2. Identify 1-2 recurring musical styles or genres in the data
3. Based on these insights, generate exactly 5 creative music prompt ideas for AI music generation

## Output Format
Return ONLY valid JSON (no markdown, no explanation):
{{
  "analysis": {{
    "dominant_moods": ["mood1", "mood2", "mood3"],
    "recurring_styles": ["style1", "style2"],
    "summary": "2-sentence summary of today's trending music landscape"
  }},
  "prompts": [
    {{
      "index": 1,
      "prompt": "A detailed, vivid music generation prompt in English, 2-3 sentences",
      "mood": "primary mood this prompt captures",
      "style_hint": "genre or style hint"
    }},
    ... (5 total)
  ]
}}
"""
    return prompt


def call_llm(token, prompt):
    print("[ai] Calling GLM-4 Flash...")
    payload = json.dumps({
        "model": GLM_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1024,
        "temperature": 0.8,
    })

    curl_cmd = [
        "curl", "-s", "-X", "POST", GLM_API,
        "-H", "Authorization: Bearer " + token,
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]

    result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"[ai] curl failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    resp = json.loads(result.stdout)
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content


def main():
    today = date.today().isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{today}.json")

    lastfm_tracks, billboard_chart = load_data(today)

    if not lastfm_tracks and not billboard_chart:
        print("[ai] ERROR: No data found. Run lastfm_fetch.py and billboard_fetch.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"[ai] Loaded {len(lastfm_tracks)} Last.fm tracks, {len(billboard_chart)} Billboard entries")

    prompt = build_prompt(lastfm_tracks, billboard_chart)

    token = os.environ.get("ZHIPU_API_KEY", "")
    if not token:
        token_path = os.path.expanduser("~/.openclaw/credentials/minimax-portal_api_key.txt")
        if os.path.exists(token_path):
            with open(token_path) as f:
                token = f.read().strip()
    if not token:
        print("[ai] ERROR: ZHIPU_API_KEY env var not set and no fallback token file", file=sys.stderr)
        sys.exit(1)

    raw_content = call_llm(token, prompt)

    content = raw_content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        content = content.rsplit("```", 1)[0]

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"[ai] ERROR: Failed to parse JSON from LLM: {e}", file=sys.stderr)
        print(f"[ai] Raw content:\n{raw_content[:500]}", file=sys.stderr)
        sys.exit(1)

    output = {"date": today, **result}

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[ai] Wrote analysis to {output_path}")
    print(f"[ai] Moods: {result.get('analysis', {}).get('dominant_moods', [])}")

    inserted_ids = []
    try:
        from supabase_client import _load_creds, _resolve_service_role_key
        creds = _load_creds()
        key = _resolve_service_role_key()
        base = creds["rest_api"]
        rows = []
        for p in result.get("prompts", []):
            rows.append({
                "date": today,
                "mood": p.get("mood", ""),
                "prompt": p.get("prompt", ""),
                "style_hint": p.get("style_hint", ""),
                "lyrics": None,
            })
        if rows:
            headers = {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            }
            body = json.dumps(rows).encode("utf-8")
            req = urllib.request.Request(f"{base}/music_ideas",
                                         data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    inserted = json.loads(resp.read().decode("utf-8"))
                inserted_ids = [r.get("id") for r in inserted]
                print(f"[ai] Supabase: inserted {len(inserted_ids)} music_ideas rows")
            except Exception as e:
                print(f"[ai] Supabase insert warning: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[ai] Supabase: skipped (init error: {e})", file=sys.stderr)

    prompts = result.get("prompts", [])
    for i, p in enumerate(prompts):
        p["idea_id"] = inserted_ids[i] if i < len(inserted_ids) else None

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output_path


if __name__ == "__main__":
    main()
