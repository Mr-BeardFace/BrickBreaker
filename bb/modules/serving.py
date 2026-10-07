"""Serving module — model serving endpoints and container logs"""

import json

from bb.core.db import now_iso, log_pull, should_use_cache
from bb.core.display import console
from rich import box
from rich.table import Table


def run_list(w, conn, profile, flags):
    module = "serving.list"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM serving_endpoints ORDER BY name").fetchall()
        console.print(f"\n[bold]Serving Endpoints[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",    style="cyan")
        t.add_column("State")
        t.add_column("Creator")
        for r in rows:
            state = r["state"] or "?"
            sc = "green" if state == "READY" else "yellow"
            t.add_row(r["name"], f"[{sc}]{state}[/{sc}]", r["creator"] or "?")
        console.print(t)
        return

    console.print("\n[bold]Serving Endpoints[/bold]\n")
    try:
        endpoints = list(w.serving_endpoints.list())
        now       = now_iso()
        t         = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",    style="cyan")
        t.add_column("State")
        t.add_column("Creator")
        for ep in endpoints:
            state = ep.state.ready.value if ep.state and ep.state.ready else "?"
            sc    = "green" if state == "READY" else "yellow"
            t.add_row(ep.name or "?", f"[{sc}]{state}[/{sc}]",
                      ep.creator or "?")
            conn.execute(
                "INSERT OR REPLACE INTO serving_endpoints VALUES (?,?,?,?,?)",
                (ep.name, state, ep.creator, None, now)
            )
        log_pull(conn, module, profile, len(endpoints))
        conn.commit()
        console.print(t)
        console.print("\n  [dim]Use 'serving get --name <n>' for config / 'serving logs --name <n>' for container logs[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_get(w, conn, profile, flags):
    name = flags.get("name") or flags.get("id")
    if not name:
        name = input("Endpoint name: ").strip()
    console.print(f"\n[bold]Serving Endpoint Config[/bold]  [dim]{name}[/dim]\n")
    try:
        ep  = w.serving_endpoints.get(name=name)
        now = now_iso()

        state = ep.state.ready.value if ep.state and ep.state.ready else "?"
        console.print(f"  State   : {state}")
        console.print(f"  Creator : {ep.creator or '?'}")

        config = ep.config
        if config:
            served = config.served_models or []
            console.print(f"\n  [bold]Served Models[/bold]  ({len(served)})")
            for m in served:
                console.print(f"    [cyan]{m.model_name}[/cyan]  v{m.model_version or '?'}")
                # environment_vars may expose secrets — unconfirmed, needs live test
                if hasattr(m, "environment_vars") and m.environment_vars:
                    console.print("    [yellow]env_vars present[/yellow]")
                    for k, v in m.environment_vars.items():
                        console.print(f"      [cyan]{k}[/cyan] = {v}")

        conn.execute(
            "INSERT OR REPLACE INTO serving_endpoints VALUES (?,?,?,?,?)",
            (ep.name, state, ep.creator, json.dumps({}), now)
        )
        conn.commit()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_logs(w, conn, profile, flags):
    name = flags.get("name") or flags.get("id")
    if not name:
        name = input("Endpoint name: ").strip()
    # model name defaults to first served model — user can override
    model = flags.get("schema") or input("Served model name (or Enter to try first): ").strip()

    if not model:
        try:
            ep     = w.serving_endpoints.get(name=name)
            config = ep.config
            if config and config.served_models:
                model = config.served_models[0].model_name
                console.print(f"  [dim]Using first served model: {model}[/dim]")
        except Exception:
            pass

    if not model:
        console.print("[red]Could not determine served model name — provide via prompt[/red]")
        return

    console.print(f"\n[bold]Container Logs[/bold]  [dim]{name}/{model}[/dim]\n")
    try:
        logs = w.serving_endpoints.logs(name=name, served_model_name=model)
        console.print(logs.logs or "(no logs)")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "list": {
        "description": "List all serving endpoints — name, state, creator",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_list,
    },
    "get": {
        "description": "Full endpoint config — served models and environment variables",
        "activity": ["info", "cred"], "type": "R", "noise": "Low",
        "prereqs": ["Endpoint name — from serving list"],
        "caveats": ["environment_vars on served models may contain secrets — unconfirmed, needs live test"],
        "flags": [("--name NAME", "Endpoint name")],
        "fn": run_get,
    },
    "logs": {
        "description": "Retrieve container logs for a served model (may leak secrets)",
        "activity": ["cred", "info"], "type": "R", "noise": "Low",
        "prereqs": ["Endpoint name", "Served model name"],
        "caveats": ["Container logs may contain printed credentials or stack traces"],
        "flags": [
            ("--name NAME",   "Endpoint name"),
            ("--schema NAME", "Served model name (uses first model if omitted)"),
        ],
        "fn": run_logs,
    },
}
