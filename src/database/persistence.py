"""
Database Persistence Manager
=============================
Handles backup and restore of portfolio.db to/from external storage.

This solves the Streamlit Cloud ephemeral filesystem problem:
  - Every Streamlit Cloud restart creates a fresh container with no database.
  - On startup, this module downloads the last-known-good database from a
    persistent store (GitHub Release asset or AWS S3).
  - On any database write, or on a schedule, the database can be pushed back.

Configuration (via Streamlit secrets.toml or environment variables):

  [database]
  backend = "github"   # "none" | "github" | "s3"

  [database.github]
  token = "ghp_your_personal_access_token"
  owner = "your-github-username"
  repo  = "fazdane-portfolio-manager"
  tag   = "db-backup"          # GitHub Release tag used as the store

  [database.s3]
  bucket            = "your-bucket-name"
  key               = "portfolio/portfolio.db"
  region            = "us-east-1"
  access_key_id     = "AKIA..."      # leave empty for IAM role auth
  secret_access_key = "..."

For local development, set backend = "none" (default) — database lives in
data/portfolio.db on disk and is never pushed anywhere.
"""

import os
import shutil
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Canonical path to the live database
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_ROOT, "data", "portfolio.db")
BACKUP_DIR = os.path.join(_ROOT, "data", "backups")


# ============================================================
# Public API
# ============================================================

def db_exists_and_has_data() -> bool:
    """
    Return True if portfolio.db exists and contains at least one table row.
    Used by app.py to decide whether to attempt a restore.
    """
    if not os.path.exists(DB_PATH):
        return False
    if os.path.getsize(DB_PATH) < 4096:
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=5)
        row = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()
        conn.close()
        return row and row[0] > 0
    except Exception:
        return False


def backup_database(reason: str = "manual") -> tuple[bool, str]:
    """
    Backup the current portfolio.db.

    Always creates a local timestamped copy in data/backups/.
    If a remote backend is configured, also uploads there.

    Args:
        reason: Short label for this backup (e.g. "pre-migration", "manual")

    Returns:
        (success, message)
    """
    if not os.path.exists(DB_PATH):
        return False, "No database file found to backup."

    # Local backup (always)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_path = os.path.join(BACKUP_DIR, f"portfolio_backup_{timestamp}.db")
    shutil.copy2(DB_PATH, local_path)
    logger.info(f"Local backup created: {local_path}")

    backend = _get_backend()
    if backend == "none":
        return True, f"Local backup only: {local_path}"
    elif backend == "github":
        ok, msg = _backup_to_github(DB_PATH, reason)
    elif backend == "s3":
        ok, msg = _backup_to_s3(DB_PATH, reason)
    else:
        return False, f"Unknown backend '{backend}'. Choose: none | github | s3"

    if ok:
        return True, f"{msg}  |  Local copy: {local_path}"
    return False, msg


def restore_database() -> tuple[bool, str]:
    """
    Download portfolio.db from the configured persistent store.

    Called at app startup when no local database is found.

    Returns:
        (success, message)
    """
    backend = _get_backend()
    if backend == "none":
        return False, (
            "No persistence backend configured (backend='none'). "
            "Starting with a fresh database."
        )
    elif backend == "github":
        return _restore_from_github(DB_PATH)
    elif backend == "s3":
        return _restore_from_s3(DB_PATH)
    else:
        return False, f"Unknown backend '{backend}'."


# ============================================================
# Backend selection
# ============================================================

def _get_backend() -> str:
    """Read the desired backend from Streamlit secrets or env."""
    try:
        import streamlit as st
        return st.secrets.get("database", {}).get("backend", "none")
    except Exception:
        return os.getenv("DB_BACKEND", "none")


# ============================================================
# GitHub Release backend
# ============================================================
# Stores portfolio.db as a release asset on a dedicated git release tag.
# Recommended for Streamlit Cloud — no extra cloud accounts needed.

def _get_github_config() -> dict:
    try:
        import streamlit as st
        gh = st.secrets.get("database", {}).get("github", {})
    except Exception:
        gh = {}
    return {
        "token": gh.get("token") or os.getenv("GH_DB_TOKEN", ""),
        "owner": gh.get("owner") or os.getenv("GH_DB_OWNER", ""),
        "repo":  gh.get("repo")  or os.getenv("GH_DB_REPO", ""),
        "tag":   gh.get("tag")   or os.getenv("GH_DB_TAG", "db-backup"),
    }


def _backup_to_github(db_path: str, reason: str) -> tuple[bool, str]:
    """Upload portfolio.db as a GitHub Release asset."""
    try:
        import requests
    except ImportError:
        return False, "requests package not installed. Run: pip install requests"

    cfg = _get_github_config()
    if not all([cfg["token"], cfg["owner"], cfg["repo"]]):
        return False, "GitHub config incomplete — need token, owner, repo in secrets.toml"

    headers = {
        "Authorization": f"token {cfg['token']}",
        "Accept": "application/vnd.github.v3+json",
    }
    base = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}"

    try:
        release_id, upload_url = _gh_get_or_create_release(headers, base, cfg["tag"])
        _gh_delete_asset(headers, base, release_id, "portfolio.db")

        with open(db_path, "rb") as fh:
            data = fh.read()

        clean_url = upload_url.replace("{?name,label}", "")
        resp = requests.post(
            clean_url,
            params={
                "name": "portfolio.db",
                "label": f"Backup: {reason} — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
            },
            headers={**headers, "Content-Type": "application/octet-stream"},
            data=data,
            timeout=120,
        )
        resp.raise_for_status()
        return True, f"Backed up to GitHub release '{cfg['tag']}' ({len(data):,} bytes)"
    except Exception as exc:
        return False, f"GitHub backup failed: {exc}"


def _restore_from_github(db_path: str) -> tuple[bool, str]:
    """Download portfolio.db from a GitHub Release asset."""
    try:
        import requests
    except ImportError:
        return False, "requests package not installed."

    cfg = _get_github_config()
    if not all([cfg["token"], cfg["owner"], cfg["repo"]]):
        return False, "GitHub config incomplete."

    headers = {
        "Authorization": f"token {cfg['token']}",
        "Accept": "application/vnd.github.v3+json",
    }
    base = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}"

    try:
        resp = requests.get(
            f"{base}/releases/tags/{cfg['tag']}",
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 404:
            return False, f"No backup release found (tag: '{cfg['tag']}'). Starting fresh."
        resp.raise_for_status()

        assets = resp.json().get("assets", [])
        db_asset = next((a for a in assets if a["name"] == "portfolio.db"), None)
        if not db_asset:
            return False, "Release exists but contains no portfolio.db asset. Starting fresh."

        dl = requests.get(
            db_asset["url"],
            headers={**headers, "Accept": "application/octet-stream"},
            timeout=120,
        )
        dl.raise_for_status()

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with open(db_path, "wb") as fh:
            fh.write(dl.content)

        return True, f"Database restored from GitHub ({len(dl.content):,} bytes)"
    except Exception as exc:
        return False, f"GitHub restore failed: {exc}"


def _gh_get_or_create_release(headers: dict, base: str, tag: str) -> tuple[int, str]:
    """Return (release_id, upload_url) for the given tag, creating the release if needed."""
    import requests
    resp = requests.get(f"{base}/releases/tags/{tag}", headers=headers, timeout=30)
    if resp.status_code == 200:
        d = resp.json()
        return d["id"], d["upload_url"]

    # Create it
    create = requests.post(
        f"{base}/releases",
        headers=headers,
        json={
            "tag_name": tag,
            "name": "Portfolio Database Backup",
            "body": (
                "⚠️ Automated database backup managed by the Portfolio Manager app.\n"
                "Do NOT delete this release — it is the persistent store for Streamlit Cloud."
            ),
            "draft": False,
            "prerelease": True,
        },
        timeout=30,
    )
    create.raise_for_status()
    d = create.json()
    return d["id"], d["upload_url"]


def _gh_delete_asset(headers: dict, base: str, release_id: int, name: str):
    """Delete an asset from a release by name (to replace it with a fresh upload)."""
    import requests
    resp = requests.get(f"{base}/releases/{release_id}/assets", headers=headers, timeout=30)
    if resp.status_code != 200:
        return
    for asset in resp.json():
        if asset["name"] == name:
            requests.delete(
                f"{base}/releases/assets/{asset['id']}",
                headers=headers,
                timeout=30,
            )


# ============================================================
# S3 backend
# ============================================================

def _get_s3_config() -> dict:
    try:
        import streamlit as st
        s3 = st.secrets.get("database", {}).get("s3", {})
    except Exception:
        s3 = {}
    return {
        "bucket":            s3.get("bucket")            or os.getenv("DB_S3_BUCKET", ""),
        "key":               s3.get("key",    "portfolio/portfolio.db"),
        "region":            s3.get("region")            or os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        "access_key_id":     s3.get("access_key_id")     or os.getenv("AWS_ACCESS_KEY_ID", ""),
        "secret_access_key": s3.get("secret_access_key") or os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    }


def _backup_to_s3(db_path: str, reason: str) -> tuple[bool, str]:
    try:
        import boto3
    except ImportError:
        return False, "boto3 not installed. Run: pip install boto3"

    cfg = _get_s3_config()
    if not cfg["bucket"]:
        return False, "S3 bucket not configured."

    try:
        s3 = boto3.client(
            "s3",
            region_name=cfg["region"],
            aws_access_key_id=cfg["access_key_id"] or None,
            aws_secret_access_key=cfg["secret_access_key"] or None,
        )
        s3.upload_file(
            db_path,
            cfg["bucket"],
            cfg["key"],
            ExtraArgs={"Metadata": {
                "backup-reason": reason,
                "timestamp": datetime.now().isoformat(),
            }},
        )
        return True, f"Backed up to s3://{cfg['bucket']}/{cfg['key']}"
    except Exception as exc:
        return False, f"S3 backup failed: {exc}"


def _restore_from_s3(db_path: str) -> tuple[bool, str]:
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        return False, "boto3 not installed."

    cfg = _get_s3_config()
    if not cfg["bucket"]:
        return False, "S3 bucket not configured."

    try:
        s3 = boto3.client(
            "s3",
            region_name=cfg["region"],
            aws_access_key_id=cfg["access_key_id"] or None,
            aws_secret_access_key=cfg["secret_access_key"] or None,
        )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        s3.download_file(cfg["bucket"], cfg["key"], db_path)
        size = os.path.getsize(db_path)
        return True, f"Restored from s3://{cfg['bucket']}/{cfg['key']} ({size:,} bytes)"
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            return False, "No database backup found in S3. Starting fresh."
        return False, f"S3 restore failed: {exc}"
    except Exception as exc:
        return False, f"S3 restore failed: {exc}"
