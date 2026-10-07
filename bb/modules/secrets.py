"""Secrets module — scopes, key names, access probing"""

from bb.core.db import now_iso, log_pull, fmt_epoch_ms, should_use_cache
from bb.core.display import console, next_step
from rich import box
from rich.table import Table


def run_scopes(w, conn, profile, flags):
    module = "secrets.scopes"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM secrets_scopes ORDER BY name").fetchall()
        console.print(f"\n[bold]Secret Scopes[/bold]  [dim](cached {age})[/dim]\n")
        for r in rows:
            access = r["access"] or ""
            ac = "  [green]READ[/green]" if access == "READ" else ("  [red]DENIED[/red]" if access == "DENIED" else "")
            console.print(f"  [cyan]{r['name']}[/cyan]  [dim]{r['backend_type'] or '?'}[/dim]{ac}")
        console.print()
        next_step("secrets list --scope <name> --run",
                  "secrets all --run")
        return

    console.print("\n[bold]Secret Scopes[/bold]\n")
    try:
        scopes = list(w.secrets.list_scopes())
        now    = now_iso()
        for s in scopes:
            bt = s.backend_type.value if s.backend_type else "?"
            console.print(f"  [cyan]{s.name}[/cyan]  [dim]{bt}[/dim]")
            conn.execute(
                "INSERT OR REPLACE INTO secrets_scopes VALUES (?,?,?,?)",
                (s.name, bt, None, now)
            )
        log_pull(conn, module, profile, len(scopes))
        conn.commit()
        console.print()
        next_step("secrets list --scope <name> --run",
                  "secrets all --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_list(w, conn, profile, flags):
    scope = flags.get("scope")
    if not scope:
        console.print("[red]--scope <name> required[/red]")
        return
    console.print(f"\n[bold]Keys in scope: {scope}[/bold]\n")
    try:
        keys = list(w.secrets.list_secrets(scope=scope))
        now  = now_iso()
        t    = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Key",          style="cyan")
        t.add_column("Last Updated")
        for k in keys:
            t.add_row(k.key, fmt_epoch_ms(k.last_updated_timestamp))
            conn.execute(
                "INSERT OR REPLACE INTO secrets_keys VALUES (?,?,?)",
                (scope, k.key, now)
            )
        conn.execute(
            "INSERT OR REPLACE INTO secrets_scopes VALUES (?,?,?,?)",
            (scope, "?", "READ", now)
        )
        log_pull(conn, f"secrets.list.{scope}", profile, len(keys))
        conn.commit()
        console.print(t)
        next_step(f"secrets get --scope {scope} --id <key> --cluster <id> --aggressive --run",
                  f"secrets dump --scope {scope} --cluster <id> --aggressive --run")
    except Exception as e:
        if "PERMISSION_DENIED" in str(e) or "permission" in str(e).lower():
            console.print(f"[yellow]  ⚠ Access denied on scope '{scope}' — no READ permission[/yellow]")
            conn.execute(
                "INSERT OR REPLACE INTO secrets_scopes VALUES (?,?,?,?)",
                (scope, "?", "DENIED", now_iso())
            )
            conn.commit()
        else:
            console.print(f"[red]Error: {e}[/red]")


def run_all(w, conn, profile, flags):
    module = "secrets.all"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        scopes = conn.execute("SELECT * FROM secrets_scopes ORDER BY name").fetchall()
        console.print(f"\n[bold]All Secret Scopes + Keys[/bold]  [dim](cached {age})[/dim]\n")
        for s in scopes:
            access = s["access"] or ""
            ac = "[green]READ[/green]" if access == "READ" else ("[red]DENIED[/red]" if access == "DENIED" else "")
            console.print(f"[cyan]{s['name']}[/cyan]  [dim]{s['backend_type'] or '?'}[/dim]  {ac}")
            keys = conn.execute(
                "SELECT * FROM secrets_keys WHERE scope=? ORDER BY key", (s["name"],)
            ).fetchall()
            for k in keys:
                console.print(f"  [dim]{k['key']}[/dim]")
        next_step("secrets get --scope <name> --id <key> --cluster <id> --aggressive --run",
                  "secrets dump --cluster <id> --aggressive --run")
        return

    total_keys = 0
    console.print("\n[bold]All Secret Scopes + Keys[/bold]\n")
    try:
        scopes = list(w.secrets.list_scopes())
        now    = now_iso()
        for s in scopes:
            bt = s.backend_type.value if s.backend_type else "?"
            console.print(f"[cyan]{s.name}[/cyan]  [dim]{bt}[/dim]")
            try:
                keys = list(w.secrets.list_secrets(scope=s.name))
                total_keys += len(keys)
                for k in keys:
                    updated = fmt_epoch_ms(k.last_updated_timestamp)
                    console.print(f"  [dim]{k.key:<45} updated={updated}[/dim]")
                    conn.execute(
                        "INSERT OR REPLACE INTO secrets_keys VALUES (?,?,?)",
                        (s.name, k.key, now)
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO secrets_scopes VALUES (?,?,?,?)",
                    (s.name, bt, "READ", now)
                )
            except Exception as inner:
                if "PERMISSION_DENIED" in str(inner) or "permission" in str(inner).lower():
                    console.print("  [yellow]⚠ access denied (no READ)[/yellow]")
                    conn.execute(
                        "INSERT OR REPLACE INTO secrets_scopes VALUES (?,?,?,?)",
                        (s.name, bt, "DENIED", now)
                    )
                else:
                    console.print(f"  [red]error: {inner}[/red]")
        log_pull(conn, module, profile, total_keys)
        conn.commit()
        next_step("secrets get --scope <name> --id <key> --cluster <id> --aggressive --run",
                  "secrets dump --cluster <id> --aggressive --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_get(w, conn, profile, flags):
    """Extract a secret value via cluster command execution (EXEC — requires --aggressive)"""
    if not flags.get("aggressive"):
        console.print("[yellow]EXEC operation — requires --aggressive flag[/yellow]")
        console.print("  [dim]Secret values are never returned by the REST API — extraction requires running a command on a cluster.[/dim]")
        return

    scope = flags.get("scope")
    key   = flags.get("id") or flags.get("name")
    cluster_id = flags.get("cluster")

    if not scope:
        scope = input("Scope (from: secrets scopes --run)  e.g. prod-api-keys: ").strip()
    if not key:
        key = input("Key (from: secrets list --scope <scope> --run)  e.g. stripe_secret_key: ").strip()
    if not cluster_id:
        cluster_id = input("Cluster ID (from: compute clusters --run)  e.g. 0123-456789-abc1def2: ").strip()

    console.print(f"\n[bold]Secret Extract[/bold]  [dim]{scope}/{key}  cluster={cluster_id}[/dim]\n")
    try:
        from databricks.sdk.service.compute import Language
        cmd = f"print(dbutils.secrets.get(scope='{scope}', key='{key}'))"
        ctx = w.command_execution.create(cluster_id=cluster_id, language=Language.PYTHON).result()
        try:
            result = w.command_execution.execute(
                cluster_id=cluster_id,
                context_id=ctx.id,
                language=Language.PYTHON,
                command=cmd,
            ).result()
            if result.results:
                value = result.results.data or "(no output)"
                console.print(f"  [cyan]{scope}/{key}[/cyan] = [yellow]{value}[/yellow]")
            else:
                console.print("[red]No result returned[/red]")
        finally:
            w.command_execution.destroy(cluster_id=cluster_id, context_id=ctx.id)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_dump(w, conn, profile, flags):
    """Dump all accessible secret values via cluster (EXEC — requires --aggressive)"""
    if not flags.get("aggressive"):
        console.print("[yellow]EXEC operation — requires --aggressive flag[/yellow]")
        return

    cluster_id = flags.get("cluster")
    scope_filter = flags.get("scope")

    if not cluster_id:
        cluster_id = input("Cluster ID (from: compute clusters --run)  e.g. 0123-456789-abc1def2: ").strip()

    console.print(f"\n[bold]Secret Dump[/bold]  [dim]cluster={cluster_id}[/dim]\n")
    try:
        scopes = list(w.secrets.list_scopes())
        if scope_filter:
            scopes = [s for s in scopes if s.name == scope_filter]

        from databricks.sdk.service.compute import Language
        ctx = w.command_execution.create(cluster_id=cluster_id, language=Language.PYTHON).result()
        try:
            hits = []
            for s in scopes:
                try:
                    keys = list(w.secrets.list_secrets(scope=s.name))
                except Exception:
                    continue
                for k in keys:
                    cmd = f"print(dbutils.secrets.get(scope='{s.name}', key='{k.key}'))"
                    try:
                        result = w.command_execution.execute(
                            cluster_id=cluster_id,
                            context_id=ctx.id,
                            language=Language.PYTHON,
                            command=cmd,
                        ).result()
                        value = (result.results.data if result.results else None) or "(empty)"
                        hits.append((s.name, k.key, value))
                    except Exception:
                        hits.append((s.name, k.key, "[red](error)[/red]"))
        finally:
            w.command_execution.destroy(cluster_id=cluster_id, context_id=ctx.id)

        if hits:
            t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
            t.add_column("Scope",  style="dim")
            t.add_column("Key",    style="cyan")
            t.add_column("Value",  style="yellow")
            extended = flags.get("extended", False)
            for scope_name, key_name, value in hits:
                t.add_row(scope_name, key_name, value if extended else value[:120])
            console.print(t)
            console.print(f"\n  [dim]{len(hits)} secret(s) extracted[/dim]")
        else:
            console.print("[yellow]No secrets extracted[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "scopes": {
        "description": "List all secret scopes and their backend type",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_scopes,
    },
    "list": {
        "description": "List all key names in a specific scope",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["Requires READ permission on the scope", "Values never returned by API"],
        "flags": [("--scope NAME", "Scope name")],
        "required_flags": ["--scope"],
        "fn": run_list,
    },
    "all": {
        "description": "List all scopes and all accessible key names in one pass",
        "activity": ["info"], "type": "R", "noise": "Low-Medium — one call per scope",
        "prereqs": [],
        "caveats": [
            "Shows ⚠ denied for scopes where READ is not granted",
            "Values never returned by API — extraction requires cluster EXEC",
        ],
        "flags": [],
        "fn": run_all,
    },
    "get": {
        "description": "Extract a single secret value by executing dbutils.secrets.get() on a cluster",
        "activity": ["cred"], "type": "EXEC", "noise": "Medium — creates command execution context",
        "prereqs": ["Running cluster ID — from compute clusters", "CAN_ATTACH_TO on cluster"],
        "caveats": [
            "Secret values are never returned by the REST API — cluster execution required",
            "Execution context visible in cluster event log",
        ],
        "flags": [
            ("--scope NAME",   "Scope name"),
            ("--id KEY",       "Key name"),
            ("--name KEY",     "Alias for --id"),
            ("--cluster ID",   "Cluster ID to execute on"),
        ],
        "required_flags": ["--scope", "--id", "--cluster"],
        "aggressive": ["Executes dbutils.secrets.get() on cluster — visible in event log"],
        "fn": run_get,
    },
    "dump": {
        "description": "Extract ALL accessible secret values across all scopes via cluster execution",
        "activity": ["cred"], "type": "EXEC", "noise": "High — one execution per key",
        "prereqs": ["Running cluster ID — from compute clusters", "CAN_ATTACH_TO on cluster"],
        "caveats": [
            "High-noise: one command execution per key",
            "Execution context visible in cluster event log",
            "Use --scope to limit to a single scope",
        ],
        "flags": [
            ("--cluster ID",  "Cluster ID to execute on"),
            ("--scope NAME",  "Limit to a single scope (optional)"),
        ],
        "required_flags": ["--cluster"],
        "aggressive": ["Executes one dbutils.secrets.get() per key — all visible in event log"],
        "fn": run_dump,
    },
}
