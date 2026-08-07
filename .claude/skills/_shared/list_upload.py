#!/usr/bin/env python3
"""Shared prospect-list uploader for Navreo skills.

Uploads a CSV of prospects into the Supabase `lists` / `list_rows` /
`list_folders` tables that back the Navreo signals-tool "Lists" UI
(https://navreo-signals.onrender.com/app/lists.html).

Design rules:
- Python 3 stdlib only (urllib, csv, json, argparse). No pip deps, no `requests`.
  (navreo_db.py in this same directory uses `requests`, which is fine for skills
  that already depend on it, but this uploader is meant to run standalone in any
  skill's venv-less environment, so it avoids third-party imports entirely.)
- Reads SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY from ~/.navreo-keys.env, mirroring
  the key-loading convention in navreo_db.py._env().
- Upsert-by-(name, client): re-running with the same name+client REUSES the list id
  and REPLACES its rows rather than creating a duplicate list.
- The only DELETE this script ever issues is scoped with `list_id=eq.<id>` in the
  URL — never an unscoped table wipe. See MEMORY: "Signals whole-table-replace
  data-loss fix" for why that matters.
"""

import argparse
import csv
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

KEYS_FILE = Path.home() / ".navreo-keys.env"
RECEIPTS = Path.home() / ".claude" / "state" / "list_uploads.jsonl"
LISTS_APP_BASE = "https://navreo-signals.onrender.com/app/lists.html"
BATCH_SIZE = 500
TIMEOUT = 30

_env_cache = None


class UploadError(RuntimeError):
    """Raised for any fatal, user-facing failure (missing keys, bad CSV, HTTP error)."""


# ---------------------------------------------------------------------------
# Key loading (mirrors navreo_db.py._env)
# ---------------------------------------------------------------------------

def _env(name):
    global _env_cache
    if _env_cache is None:
        _env_cache = {}
        if not KEYS_FILE.exists():
            raise UploadError(
                f"Keys file not found: {KEYS_FILE}. Expected SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY as KEY=VALUE lines."
            )
        for line in KEYS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line[len("export "):] if line.startswith("export ") else line
            if "=" in line:
                k, _, v = line.partition("=")
                _env_cache[k.strip()] = v.strip().strip('"').strip("'")
    val = _env_cache.get(name)
    if not val:
        raise UploadError(f"{name} missing from {KEYS_FILE}")
    return val


def _base_and_key():
    url = _env("SUPABASE_URL").rstrip("/")
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    return url, key


# ---------------------------------------------------------------------------
# Minimal PostgREST client (requests, matching _shared/navreo_db.py — its
# bundled CA store works where the system urllib cert chain does not)
# ---------------------------------------------------------------------------

def _request(method, path, params=None, payload=None, prefer=None):
    """One PostgREST call. Returns parsed JSON body (list/dict) or None for empty 2xx.

    Raises UploadError with status + body on any HTTP error.
    """
    import requests

    url, key = _base_and_key()
    full_url = f"{url}{path}"

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    try:
        resp = requests.request(method, full_url, params=params or None,
                                json=payload, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise UploadError(f"Network error on {method} {path}: {e}") from e
    if resp.status_code >= 400:
        raise UploadError(f"HTTP {resp.status_code} on {method} {path}: {resp.text}")
    if not resp.content:
        return None
    return resp.json()


def _get_one(path, params):
    rows = _request("GET", path, params=params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Folder handling
# ---------------------------------------------------------------------------

def _ensure_root_folder(client):
    """Find or create the client's ROOT folder (name IS NULL, parent_id IS NULL)."""
    existing = _get_one(
        "/rest/v1/list_folders",
        {
            "client": f"eq.{client}",
            "name": "is.null",
            "parent_id": "is.null",
            "select": "id",
            "limit": "1",
        },
    )
    if existing:
        return existing["id"]

    created = _request(
        "POST",
        "/rest/v1/list_folders",
        prefer="return=representation",
        payload={"client": client, "name": None, "parent_id": None},
    )
    if not created:
        raise UploadError(f"Failed to create root folder for client {client!r}")
    return created[0]["id"]


def _ensure_sub_folder(client, root_id, folder_name):
    """Find or create a theme sub-folder under root_id. Never nests deeper than 2 levels."""
    existing = _get_one(
        "/rest/v1/list_folders",
        {
            "client": f"eq.{client}",
            "name": f"eq.{folder_name}",
            "parent_id": f"eq.{root_id}",
            "select": "id",
            "limit": "1",
        },
    )
    if existing:
        return existing["id"]

    created = _request(
        "POST",
        "/rest/v1/list_folders",
        prefer="return=representation",
        payload={"client": client, "name": folder_name, "parent_id": root_id},
    )
    if not created:
        raise UploadError(f"Failed to create sub-folder {folder_name!r} for {client!r}")
    return created[0]["id"]


def resolve_folder_id(client, folder=None):
    root_id = _ensure_root_folder(client)
    if folder:
        return _ensure_sub_folder(client, root_id, folder)
    return root_id


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_csv(csv_path):
    path = Path(csv_path)
    if not path.exists():
        raise UploadError(f"CSV not found: {csv_path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise UploadError(f"CSV has no header row: {csv_path}")
        columns = list(reader.fieldnames)
        rows = [dict(row) for row in reader]

    if not rows:
        raise UploadError(f"CSV is empty (no data rows): {csv_path}")

    return columns, rows


# ---------------------------------------------------------------------------
# List upsert
# ---------------------------------------------------------------------------

def _find_existing_list(name, client):
    return _get_one(
        "/rest/v1/lists",
        {
            "name": f"eq.{name}",
            "client": f"eq.{client}",
            "select": "id",
            "limit": "1",
        },
    )


def _delete_list_rows(list_id):
    """Delete only this list's rows. The filter MUST be present — never an unscoped delete."""
    params = {"list_id": f"eq.{list_id}"}
    # Belt-and-braces: refuse to send the request if the scoping filter somehow
    # isn't there (e.g. list_id came back empty/None).
    if "list_id=eq." not in urllib.parse.urlencode(params) or not list_id:
        raise UploadError(
            "Refusing to delete list_rows: scoping filter list_id=eq.<id> missing."
        )
    _request("DELETE", "/rest/v1/list_rows", params=params)


def _insert_rows(list_id, columns, rows):
    inserted = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        payload = [
            {
                "list_id": list_id,
                "row_num": i + offset + 1,
                "data": {col: row.get(col) for col in columns},
            }
            for offset, row in enumerate(batch)
        ]
        _request("POST", "/rest/v1/list_rows", payload=payload)
        inserted += len(batch)
    return inserted


def _content_hash(csv_path):
    """Stable hash of a CSV's bytes — the key the autopush guard matches on."""
    import hashlib
    return hashlib.sha256(Path(csv_path).read_bytes()).hexdigest()


def _write_receipt(csv_path, list_id, name, client, rows, link):
    """Append an upload receipt so the list-autopush Stop hook can prove this CSV shipped.

    Best-effort: a receipt failure must never break a successful upload.
    """
    try:
        import time
        RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "csv_path": str(Path(csv_path).resolve()),
            "content_sha256": _content_hash(csv_path),
            "list_id": list_id, "name": name, "client": client,
            "rows": rows, "link": link, "uploaded_at": time.time(),
        }
        with RECEIPTS.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def upload_list(csv_path, name, client, folder=None, source_skill=None,
                 brief_context=None, owner=None):
    """Upload (or replace) a prospect list. Returns the lists.html link string."""
    if not name:
        raise UploadError("name is required")
    if not client:
        raise UploadError("client is required")

    columns, rows = load_csv(csv_path)
    folder_id = resolve_folder_id(client, folder)

    existing = _find_existing_list(name, client)

    list_row = {
        "name": name,
        "client": client,
        "folder_id": folder_id,
        "source_skill": source_skill,
        "owner": owner,
        "brief_context": brief_context,
        "row_count": len(rows),
        "columns": columns,
    }

    if existing:
        list_id = existing["id"]
        _request(
            "PATCH",
            "/rest/v1/lists",
            params={"id": f"eq.{list_id}"},
            payload=list_row,
        )
        _delete_list_rows(list_id)
    else:
        created = _request(
            "POST",
            "/rest/v1/lists",
            prefer="return=representation",
            payload=list_row,
        )
        if not created:
            raise UploadError(f"Failed to create list {name!r} for {client!r}")
        list_id = created[0]["id"]

    inserted = _insert_rows(list_id, columns, rows)

    # Row count is set from len(rows) above; confirm it matches what we actually
    # inserted and correct it via PATCH if a batch partially failed silently.
    if inserted != len(rows):
        _request(
            "PATCH",
            "/rest/v1/lists",
            params={"id": f"eq.{list_id}"},
            payload={"row_count": inserted},
        )

    link = f"{LISTS_APP_BASE}#{list_id}"

    _write_receipt(csv_path, list_id, name, client, inserted, link)

    print(f"List: {name}")
    print(f"Client: {client}")
    print(f"Folder: {folder or '(root)'}")
    print(f"Rows: {inserted}")
    print(f"Link: {link}")

    return link


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Upload a prospect-list CSV into the Navreo signals-tool Lists UI."
    )
    parser.add_argument("csv_path", help="Path to the CSV file to upload")
    parser.add_argument("--name", required=True, help="List name")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--folder", default=None, help="Optional theme sub-folder name")
    parser.add_argument("--source-skill", dest="source_skill", default=None,
                         help="Name of the skill that produced this list")
    parser.add_argument("--brief", dest="brief_context", default=None,
                         help="Free-text brief/context for this list")
    parser.add_argument("--owner", default=None, help="Owner name")

    args = parser.parse_args(argv)

    try:
        upload_list(
            csv_path=args.csv_path,
            name=args.name,
            client=args.client,
            folder=args.folder,
            source_skill=args.source_skill,
            brief_context=args.brief_context,
            owner=args.owner,
        )
    except UploadError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
