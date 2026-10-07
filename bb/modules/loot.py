"""Loot module — aggregated high-value findings from local cache"""

import json

from bb.core.display import console, next_step
from bb.core.crypto import decrypt
from rich import box
from rich.table import Table


def _section(title: str, count: int):
    console.print(f"\n  [bold yellow]{title}[/bold yellow]  [dim]({count})[/dim]")


def run_dump(w, conn, profile, flags):
    console.print(f"\n[bold]Loot[/bold]  [dim]profile={profile}  (local cache only — R*)[/dim]\n")

    found_anything = False

    # ── Secrets ──────────────────────────────────────────────────────────────
    scopes = conn.execute("SELECT name FROM secrets_scopes ORDER BY name").fetchall()
    keys   = conn.execute(
        "SELECT scope, key FROM secrets_keys ORDER BY scope, key"
    ).fetchall()
    if scopes:
        found_anything = True
        keys_by_scope: dict = {}
        for r in keys:
            keys_by_scope.setdefault(r["scope"], []).append(r["key"])
        _section("SECRETS", len(scopes))
        for s in scopes:
            name = s["name"]
            ks   = keys_by_scope.get(name, [])
            kstr = ", ".join(ks) if ks else "[dim](no keys pulled)[/dim]"
            console.print(f"    [cyan]{name}[/cyan]  →  {kstr}")
        console.print("    [dim]Values require cluster execution — use secrets dump --run[/dim]")

    # ── UC Connections ────────────────────────────────────────────────────────
    conns = conn.execute(
        "SELECT name, connection_type, options_json FROM uc_connections ORDER BY name"
    ).fetchall()
    if conns:
        found_anything = True
        _section("UC CONNECTIONS", len(conns))
        for r in conns:
            raw = decrypt(profile, r["options_json"] or "")
            console.print(f"    [cyan]{r['name']}[/cyan]  [dim]{r['connection_type'] or '?'}[/dim]")
            if raw and raw != "{}":
                try:
                    opts = json.loads(raw)
                    for k, v in opts.items():
                        console.print(f"      [dim]{k}[/dim] = [yellow]{v}[/yellow]")
                except Exception:
                    console.print(f"      {raw}")
            else:
                console.print("      [dim](no options stored — run uc connections-get --run to pull)[/dim]")

    # ── UC Storage Credentials ────────────────────────────────────────────────
    stor = conn.execute(
        "SELECT name, aws_arn, az_dir_id FROM uc_storage_credentials ORDER BY name"
    ).fetchall()
    if stor:
        found_anything = True
        _section("UC STORAGE CREDENTIALS", len(stor))
        for r in stor:
            detail = r["aws_arn"] or r["az_dir_id"] or "[dim]?[/dim]"
            console.print(f"    [cyan]{r['name']}[/cyan]  {detail}")

    # ── UC External Locations ─────────────────────────────────────────────────
    locs = conn.execute(
        "SELECT name, url, credential FROM uc_external_locations ORDER BY name"
    ).fetchall()
    if locs:
        found_anything = True
        _section("UC EXTERNAL LOCATIONS", len(locs))
        for r in locs:
            cred = f"  [dim]cred: {r['credential']}[/dim]" if r["credential"] else ""
            console.print(f"    [cyan]{r['url'] or r['name']}[/cyan]{cred}")

    # ── Git Credentials ───────────────────────────────────────────────────────
    git = conn.execute(
        "SELECT git_username, git_provider, COUNT(*) as cnt "
        "FROM git_credentials GROUP BY git_username, git_provider ORDER BY git_username"
    ).fetchall()
    if git:
        found_anything = True
        _section("GIT CREDENTIALS", sum(r["cnt"] for r in git))
        for r in git:
            ct = f"  [dim]×{r['cnt']}[/dim]" if r["cnt"] > 1 else ""
            console.print(f"    [cyan]{r['git_username'] or '?'}[/cyan]  [dim]{r['git_provider'] or '?'}[/dim]{ct}")
        console.print("    [dim]Token values are never returned by the API[/dim]")

    # ── Cluster Instance Profiles (IAM) ───────────────────────────────────────
    clust = conn.execute(
        "SELECT cluster_name, instance_profile FROM clusters "
        "WHERE instance_profile IS NOT NULL AND instance_profile != '' ORDER BY cluster_name"
    ).fetchall()
    if clust:
        found_anything = True
        _section("CLUSTER INSTANCE PROFILES (IAM)", len(clust))
        for r in clust:
            console.print(f"    [cyan]{r['cluster_name'] or '?'}[/cyan]  {r['instance_profile']}")

    # ── Job Spark Env Vars ────────────────────────────────────────────────────
    jenv = conn.execute(
        "SELECT j.name, jc.spark_env_vars FROM job_configs jc "
        "JOIN jobs j ON j.job_id = jc.job_id "
        "WHERE jc.spark_env_vars IS NOT NULL AND jc.spark_env_vars != '' ORDER BY j.name"
    ).fetchall()
    if jenv:
        found_anything = True
        shown = 0
        for r in jenv:
            raw = decrypt(profile, r["spark_env_vars"])
            try:
                env = json.loads(raw)
            except Exception:
                continue
            if not env:
                continue
            if shown == 0:
                _section("JOB SPARK ENV VARS", len(jenv))
            shown += 1
            console.print(f"    [cyan]{r['name'] or '?'}[/cyan]")
            for k, v in env.items():
                console.print(f"      [dim]{k}[/dim] = [yellow]{v}[/yellow]")
        if shown == 0:
            _section("JOB SPARK ENV VARS (no values)", len(jenv))
            for r in jenv:
                console.print(f"    [cyan]{r['name'] or '?'}[/cyan]  [dim](empty)[/dim]")

    # ── Init Scripts with Content ─────────────────────────────────────────────
    inits = conn.execute(
        "SELECT name, script_id, content FROM init_scripts "
        "WHERE content IS NOT NULL AND content != '' ORDER BY name"
    ).fetchall()
    if inits:
        found_anything = True
        _section("INIT SCRIPTS (content pulled)", len(inits))
        for r in inits:
            content = decrypt(profile, r["content"])
            lines   = content.splitlines()
            preview = lines[0][:80] if lines else ""
            size    = f"{len(lines)} lines"
            console.print(f"    [cyan]{r['name'] or r['script_id']}[/cyan]  [dim]{size}[/dim]")
            if preview:
                console.print(f"      [dim]{preview}[/dim]")
        console.print("    [dim]Full content: compute init-script-get --id <id> --run[/dim]")

    # ── Saved Queries ─────────────────────────────────────────────────────────
    queries = conn.execute(
        "SELECT name, query_text FROM saved_queries "
        "WHERE query_text IS NOT NULL AND query_text != '' ORDER BY name"
    ).fetchall()
    if queries:
        found_anything = True
        _section("SAVED QUERIES", len(queries))
        for r in queries:
            lines   = (r["query_text"] or "").splitlines()
            preview = lines[0][:80] if lines else ""
            console.print(f"    [cyan]{r['name'] or '?'}[/cyan]  [dim]{len(lines)} lines[/dim]")
            if preview:
                console.print(f"      [dim]{preview}[/dim]")
        console.print("    [dim]Full text: sql queries-get --id <id> --run  ·  loot scan to pattern-match[/dim]")

    # ── Exported Notebooks ────────────────────────────────────────────────────
    if _table_exists(conn, "notebook_content"):
        nbs = conn.execute(
            "SELECT path, pulled_at FROM notebook_content ORDER BY path"
        ).fetchall()
        if nbs:
            found_anything = True
            _section("EXPORTED NOTEBOOKS (run loot scan to search for creds)", len(nbs))
            for r in nbs:
                console.print(f"    [cyan]{r['path']}[/cyan]  [dim]{r['pulled_at'][:10]}[/dim]")

    # ── Tokens ────────────────────────────────────────────────────────────────
    toks = conn.execute(
        "SELECT token_id, comment FROM tokens ORDER BY comment"
    ).fetchall()
    if toks:
        found_anything = True
        _section("TOKENS (metadata — values never returned by API)", len(toks))
        for r in toks:
            console.print(f"    [dim]{r['token_id']}[/dim]  {r['comment'] or '[dim](no comment)[/dim]'}")

    if not found_anything:
        console.print("  [dim]Nothing cached yet — run some module commands first[/dim]")
        next_step("recon quick --run",
                  "secrets scopes --run",
                  "uc connections --run",
                  "jobs list --run")
        return

    console.print()
    next_step("secrets dump --run",
              "uc connections-get --name <name> --run",
              "jobs get --id <id> --run",
              "compute init-script-get --id <id> --run")


_CRED_PATTERNS = [
    # AWS
    ("AWS key ID",       r"AKIA[0-9A-Z]{16}"),
    ("AWS secret",       r"(?i)(aws.{0,20}secret|secret.{0,20}aws).{0,10}['\"][0-9a-zA-Z/+]{40}['\"]"),
    # Databricks PAT
    ("Databricks PAT",   r"dapi[0-9a-f]{32}"),
    # GitHub
    ("GitHub token",     r"ghp_[0-9A-Za-z]{36}"),
    ("GitHub fine-grained", r"github_pat_[0-9A-Za-z_]{82}"),
    # Azure
    ("Azure client secret", r"(?i)(client.?secret|AZURE.{0,20}SECRET).{0,10}['\"][\w~\-\.]{34,}['\"]"),
    ("Azure storage key",   r"(?i)(AccountKey=)[A-Za-z0-9+/]{86}=="),
    # Slack
    ("Slack webhook",    r"https://hooks\.slack\.com/services/[A-Z0-9]+/[A-Z0-9]+/[A-Za-z0-9]+"),
    # HuggingFace
    ("HuggingFace",      r"hf_[0-9A-Za-z]{34}"),
    # Generic high-entropy patterns (key=value style)
    ("password/secret",  r"(?i)(password|passwd|secret|token|api.?key|apikey|client.?secret)\s*[=:]\s*['\"]?[^\s'\",;]{8,}"),
]


def _scan_text(text: str, location: str, source: str, hits: list):
    import re
    for name, pat in _CRED_PATTERNS:
        for m in re.finditer(pat, text):
            line_no = text[:m.start()].count("\n") + 1
            value   = m.group(0)[:80]
            hits.append((source, location, line_no, value))
            break  # one hit per pattern per location to avoid noise


def run_scan(w, conn, profile, flags):
    import re
    console.print(f"\n[bold]Credential Scan[/bold]  [dim]profile={profile}  (local cache only — R*)[/dim]\n")

    hits: list = []

    # Job spark env vars
    rows = conn.execute(
        "SELECT j.name, jc.spark_env_vars FROM job_configs jc "
        "JOIN jobs j ON j.job_id = jc.job_id "
        "WHERE jc.spark_env_vars IS NOT NULL AND jc.spark_env_vars != ''"
    ).fetchall()
    for r in rows:
        raw = decrypt(profile, r["spark_env_vars"])
        try:
            env = json.loads(raw)
        except Exception:
            continue
        for k, v in env.items():
            if v:
                _scan_text(f"{k} = {v}", f"{r['name']}/{k}", "job-env-var", hits)

    # Saved query text
    rows = conn.execute(
        "SELECT name, query_text FROM saved_queries WHERE query_text IS NOT NULL AND query_text != ''"
    ).fetchall()
    for r in rows:
        _scan_text(r["query_text"], r["name"] or "?", "saved-query", hits)

    # Exported notebook content (workspace_items only has paths — need exported content from dbfs/workspace)
    # Notebooks are stored when exported via workspace export; check for any saved content in cache
    # We scan init script content as "script" source
    rows = conn.execute(
        "SELECT name, script_id, content FROM init_scripts WHERE content IS NOT NULL AND content != ''"
    ).fetchall()
    for r in rows:
        content = decrypt(profile, r["content"])
        _scan_text(content, r["name"] or r["script_id"], "init-script", hits)

    # UC connection options
    rows = conn.execute(
        "SELECT name, options_json FROM uc_connections WHERE options_json IS NOT NULL AND options_json != ''"
    ).fetchall()
    for r in rows:
        raw = decrypt(profile, r["options_json"])
        _scan_text(raw, r["name"], "uc-connection", hits)

    # Notebook content — stored if workspace export was run
    rows = conn.execute(
        "SELECT path, content FROM notebook_content WHERE content IS NOT NULL"
    ).fetchall() if _table_exists(conn, "notebook_content") else []
    for r in rows:
        _scan_text(decrypt(profile, r["content"]), r["path"], "notebook", hits)

    if not hits:
        console.print("  [dim]No credential patterns found in cached data[/dim]")
        console.print("  [dim]To scan notebook content: workspace export --path <path> --run[/dim]")
        return

    console.print(f"  [yellow]{len(hits)} potential credential(s) found[/yellow]\n")

    t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
    t.add_column("Source",   style="dim", no_wrap=True)
    t.add_column("Location", style="cyan")
    t.add_column("Line",     justify="right", style="dim")
    t.add_column("Value")
    for source, location, line_no, value in hits:
        t.add_row(source, location, str(line_no), value)
    console.print(t)
    console.print()
    next_step("loot dump --run",
              "workspace export --path <path> --run",
              "compute init-script-get --id <id> --run")


def _table_exists(conn, name: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(r)


COMMANDS = {
    "dump": {
        "description": "Show all cached high-value findings — secrets, creds, env vars, IAM",
        "activity": ["cred", "info"], "type": "R*", "noise": "None (local cache only)",
        "prereqs": ["Run module commands first to populate cache"],
        "caveats": [
            "Reads local SQLite cache only — no API calls",
            "Sensitive values stored encrypted at rest (Fernet, per-profile key in ~/.brickbreaker/<profile>.key)",
            "Secret values require cluster execution to retrieve — Databricks API limitation",
            "Token values are never returned by the Databricks API",
        ],
        "flags": [],
        "fn": run_dump,
    },
    "scan": {
        "description": "Regex-scan cached data for credential patterns — job env vars, queries, init scripts",
        "activity": ["cred"], "type": "R*", "noise": "None (local cache only)",
        "prereqs": ["Run module commands first to populate cache"],
        "caveats": [
            "Pattern matching only — verify hits manually before acting",
            "Notebook content scanned only if previously exported via workspace export --run",
        ],
        "flags": [],
        "fn": run_scan,
    },
}
