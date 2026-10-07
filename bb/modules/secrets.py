"""Secrets module — scopes, key names, access probing"""

from bb.core.db import now_iso, log_pull, fmt_epoch_ms, should_use_cache
from bb.core.display import console
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
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Scope Name",   style="cyan")
        t.add_column("Backend Type")
        t.add_column("Access")
        for r in rows:
            access = r["access"] or ""
            ac = "[green]READ[/green]" if access == "READ" else ("[red]DENIED[/red]" if access == "DENIED" else "")
            t.add_row(r["name"], r["backend_type"] or "?", ac)
        console.print(t)
        return

    console.print("\n[bold]Secret Scopes[/bold]\n")
    try:
        scopes = list(w.secrets.list_scopes())
        now    = now_iso()
        t      = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Scope Name",   style="cyan")
        t.add_column("Backend Type")
        for s in scopes:
            bt = s.backend_type.value if s.backend_type else "?"
            t.add_row(s.name, bt)
            conn.execute(
                "INSERT OR REPLACE INTO secrets_scopes VALUES (?,?,?,?)",
                (s.name, bt, None, now)
            )
        log_pull(conn, module, profile, len(scopes))
        conn.commit()
        console.print(t)
        console.print("\n  [dim]Use 'secrets list --scope <name>' to list keys[/dim]")
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
        console.print(f"\n  [dim]Use 'secrets get --scope {scope} --id <key>' to extract value (cluster required)[/dim]")
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
        "flags": [("--scope NAME", "Scope name (required)")],
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
}
