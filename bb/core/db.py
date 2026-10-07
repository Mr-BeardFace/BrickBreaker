"""SQLite store — one DB per profile at ~/.brickbreaker/<profile>.db"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bb.core.config import CONFIG_DIR, ensure_config_dir


def db_path(profile: str) -> Path:
    ensure_config_dir()
    return CONFIG_DIR / f"{profile}.db"


def get_db(profile: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(profile))
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pulls (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            module    TEXT NOT NULL,
            pulled_at TEXT NOT NULL,
            row_count INTEGER,
            profile   TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
            id           TEXT PRIMARY KEY,
            user_name    TEXT,
            display_name TEXT,
            email        TEXT,
            groups_json  TEXT,
            is_admin     INTEGER,
            active       INTEGER,
            pulled_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS groups (
            id           TEXT PRIMARY KEY,
            display_name TEXT,
            member_count INTEGER,
            members_json TEXT,
            pulled_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS service_principals (
            id             TEXT PRIMARY KEY,
            application_id TEXT,
            display_name   TEXT,
            active         INTEGER,
            pulled_at      TEXT
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token_id      TEXT PRIMARY KEY,
            comment       TEXT,
            creation_time INTEGER,
            expiry_time   INTEGER,
            pulled_at     TEXT
        );
        CREATE TABLE IF NOT EXISTS ip_access_lists (
            list_id      TEXT PRIMARY KEY,
            label        TEXT,
            list_type    TEXT,
            ip_addresses TEXT,
            enabled      INTEGER,
            pulled_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS secrets_scopes (
            name         TEXT PRIMARY KEY,
            backend_type TEXT,
            access       TEXT,
            pulled_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS secrets_keys (
            scope     TEXT,
            key       TEXT,
            pulled_at TEXT,
            PRIMARY KEY (scope, key)
        );
        CREATE TABLE IF NOT EXISTS clusters (
            cluster_id              TEXT PRIMARY KEY,
            cluster_name            TEXT,
            owner                   TEXT,
            instance_profile        TEXT,
            autotermination_minutes INTEGER,
            last_activity_time      INTEGER,
            pulled_at               TEXT
        );
        CREATE TABLE IF NOT EXISTS init_scripts (
            script_id TEXT PRIMARY KEY,
            name      TEXT,
            position  INTEGER,
            enabled   INTEGER,
            content   TEXT,
            pulled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs (
            job_id    TEXT PRIMARY KEY,
            name      TEXT,
            creator   TEXT,
            schedule  TEXT,
            pulled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS job_configs (
            job_id         TEXT PRIMARY KEY,
            config_json    TEXT,
            spark_env_vars TEXT,
            git_source     TEXT,
            pulled_at      TEXT
        );
        CREATE TABLE IF NOT EXISTS workspace_items (
            path      TEXT PRIMARY KEY,
            item_type TEXT,
            language  TEXT,
            object_id TEXT,
            pulled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS git_credentials (
            credential_id TEXT PRIMARY KEY,
            git_username  TEXT,
            git_provider  TEXT,
            pulled_at     TEXT
        );
        CREATE TABLE IF NOT EXISTS repos (
            id        TEXT PRIMARY KEY,
            url       TEXT,
            provider  TEXT,
            branch    TEXT,
            path      TEXT,
            pulled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS uc_catalogs (
            name      TEXT PRIMARY KEY,
            owner     TEXT,
            comment   TEXT,
            pulled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS uc_schemas (
            full_name TEXT PRIMARY KEY,
            catalog   TEXT,
            name      TEXT,
            owner     TEXT,
            pulled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS uc_tables (
            full_name   TEXT PRIMARY KEY,
            catalog     TEXT,
            schema_name TEXT,
            name        TEXT,
            table_type  TEXT,
            data_source TEXT,
            pulled_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS uc_external_locations (
            name       TEXT PRIMARY KEY,
            url        TEXT,
            credential TEXT,
            pulled_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS uc_storage_credentials (
            name      TEXT PRIMARY KEY,
            aws_arn   TEXT,
            az_dir_id TEXT,
            pulled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS uc_connections (
            name            TEXT PRIMARY KEY,
            connection_type TEXT,
            options_json    TEXT,
            pulled_at       TEXT
        );
        CREATE TABLE IF NOT EXISTS warehouses (
            warehouse_id TEXT PRIMARY KEY,
            name         TEXT,
            cluster_size TEXT,
            state        TEXT,
            creator      TEXT,
            pulled_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS saved_queries (
            query_id   TEXT PRIMARY KEY,
            name       TEXT,
            query_text TEXT,
            created_by TEXT,
            pulled_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS serving_endpoints (
            name        TEXT PRIMARY KEY,
            state       TEXT,
            creator     TEXT,
            config_json TEXT,
            pulled_at   TEXT
        );
    """)
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_age(conn: sqlite3.Connection, module: str) -> Optional[str]:
    row = conn.execute(
        "SELECT pulled_at FROM pulls WHERE module=? ORDER BY pulled_at DESC LIMIT 1",
        (module,)
    ).fetchone()
    if not row:
        return None
    pulled = datetime.fromisoformat(row["pulled_at"]).replace(tzinfo=timezone.utc)
    secs   = int((datetime.now(timezone.utc) - pulled).total_seconds())
    if secs < 60:    return f"{secs}s ago"
    if secs < 3600:  return f"{secs//60}m ago"
    if secs < 86400: return f"{secs//3600}h ago"
    return f"{secs//86400}d ago"


def log_pull(conn: sqlite3.Connection, module: str, profile: str, row_count: int):
    conn.execute(
        "INSERT INTO pulls (module, pulled_at, row_count, profile) VALUES (?,?,?,?)",
        (module, now_iso(), row_count, profile)
    )
    conn.commit()


def should_use_cache(conn, module: str, flags: dict) -> tuple:
    """Return (use_cache: bool, age_str: str|None).
    True when cache exists and --fresh was not passed.
    --cached forces True even if stale; returns (False, None) only when no data exists.
    """
    if flags.get("fresh"):
        return False, None
    age = cache_age(conn, module)
    if not age:
        if flags.get("cached"):
            return None, None  # caller should print "no cache" error
        return False, None
    return True, age


def fmt_epoch_ms(ts) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"
