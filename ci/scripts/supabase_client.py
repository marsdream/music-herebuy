"""
supabase_client.py — Shared Supabase REST API helper for the music-herebuy pipeline.
Insert/update rows into Supabase tables. Failures are warnings only; local JSON output is unaffected.
"""

import json
import os
import sys
import urllib.request
import urllib.error

CREDENTIALS_PATH = os.path.expanduser("~/.openclaw/credentials/supabase.json")

# Lookup tables mapping display names -> uuid (seeds from dependency task t_c6bc96fe)
USER_MAP = {"marsdream": "0f662d13-aa7d-4efb-bc92-fb09a8bc3a92"}
AGENT_MAP = {
    "Yuki": "240bbebb-1960-4a07-97a9-7a5840ed3adc",
    "hermes": "240bbebb-1960-4a07-97a9-7a5840ed3adc",
}


def _load_creds():
    with open(CREDENTIALS_PATH) as f:
        return json.load(f)


def _request(url, method="POST", data=None):
    """Fire-and-forget-ish: try the API call, return (ok, response_body, err)."""
    creds = _load_creds()
    # For service_role insertions we need a proper service_role JWT key.
    # supabase.json only has personal_access_token. Resolve the service_role
    # key via the Supabase management API on first use (cached to disk).
    srv_key = _resolve_service_role_key()

    headers = {
        "apikey": srv_key,
        "Authorization": f"Bearer {srv_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            return True, resp_body, None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return False, detail, f"HTTP {e.code}"
    except Exception as e:
        return False, "", repr(e)


# Cache service_role JWT key to avoid re-fetching from management API every run
_SRV_KEY_PATH = os.path.expanduser("~/.openclaw/credentials/supabase_service_role_key.txt")


def _resolve_service_role_key():
    if os.path.exists(_SRV_KEY_PATH):
        with open(_SRV_KEY_PATH) as f:
            v = f.read().strip()
            if v:
                return v
    # Fetch from management API
    creds = _load_creds()
    pat = creds.get("personal_access_token", "")
    if not pat:
        raise RuntimeError("personal_access_token missing from supabase.json")
    mgmt_url = "https://api.supabase.com/v1/projects/adfirxacvkcoasbujbgo/api-keys"
    req = urllib.request.Request(mgmt_url, headers={"Authorization": f"Bearer {pat}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            keys = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"Failed to fetch service_role key from management API: {e}") from e
    for k in keys:
        if k.get("name") == "service_role" and k.get("type") == "legacy":
            srv = k.get("api_key", "")
            if srv:
                os.makedirs(os.path.dirname(_SRV_KEY_PATH), exist_ok=True)
                with open(_SRV_KEY_PATH, "w") as f:
                    f.write(srv)
                return srv
    raise RuntimeError("service_role legacy key not found from management API")


def insert_into(table, row):
    """
    Insert a single row into `table`.
    Returns True on success, logs a warning on failure and returns False.
    Does NOT raise.
    """
    creds = _load_creds()
    url = f"{creds['rest_api']}/{table}"
    ok, body, err = _request(url, "POST", row)
    if ok:
        return True
    print(f"[supabase] WARNING: failed to insert into {table}: {err} {body[:200]}", file=sys.stderr)
    return False


def upsert(table, on_conflict_key, row):
    """
    Insert-or-update using Prefer header.
    """
    creds = _load_creds()
    url = f"{creds['rest_api']}/{table}"
    headers = {
        "apikey": _resolve_service_role_key(),
        "Authorization": f"Bearer {_resolve_service_role_key()}",
        "Content-Type": "application/json",
        "Prefer": f"resolution=merge-action, return=minimal",
    }
    # Set on_conflict via query param
    req_url = f"{url}?on_conflict={on_conflict_key}"
    body = json.dumps(row).encode("utf-8")
    req = urllib.request.Request(req_url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"[supabase] WARNING: upsert {table}: HTTP {e.code} {detail[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[supabase] WARNING: upsert {table}: {e}", file=sys.stderr)
        return False


def update_by_column(table, where_col, where_val, updates):
    """
    Patch rows where `where_col` == `where_val`.
    """
    creds = _load_creds()
    url = f"{creds['rest_api']}/{table}?{where_col}=eq.{where_val}"
    ok, body, err = _request(url, "PATCH", updates)
    if ok:
        return True
    print(f"[supabase] WARNING: update {table}: {err} {body[:200]}", file=sys.stderr)
    return False


def bulk_insert(table, rows):
    """Insert multiple rows (POST array). Returns count of successful inserts."""
    creds = _load_creds()
    url = f"{creds['rest_api']}/{table}"
    headers = {
        "apikey": _resolve_service_role_key(),
        "Authorization": f"Bearer {_resolve_service_role_key()}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    body = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"[supabase] WARNING: bulk insert {table}: HTTP {e.code} {detail[:300]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[supabase] WARNING: bulk insert {table}: {e}", file=sys.stderr)
        return False


def delete_where(table, filters):
    """
    Delete rows from `table` matching the filter dict.
    filters: dict of col=val, joined with AND.
    Returns True on success (or no rows affected), False on error.
    """
    creds = _load_creds()
    url = f"{creds['rest_api']}/{table}"
    conditions = "&".join(f"{col}=eq.{val}" for col, val in filters.items())
    req_url = f"{url}?{conditions}"
    ok, body, err = _request(req_url, "DELETE", None)
    if ok:
        return True
    print(f"[supabase] WARNING: delete {table}: {err} {body[:200]}", file=sys.stderr)
    return False


def resolve_user(name):
    v = USER_MAP.get(name)
    if v:
        return v
    print(f"[supabase] WARNING: unknown user '{name}' — music_generations.user_id will be NULL", file=sys.stderr)
    return None


def resolve_agent(name):
    v = AGENT_MAP.get(name)
    if v:
        return v
    print(f"[supabase] WARNING: unknown agent '{name}' — music_generations.agent_id will be NULL", file=sys.stderr)
    return None
