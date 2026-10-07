"""SQL module — warehouses, queries, query history, statement execution"""

import json

from bb.core.db import now_iso, log_pull, fmt_epoch_ms, should_use_cache
from bb.core.display import console, next_step
from bb.core.flags import limit
from rich import box
from rich.table import Table


def run_warehouses(w, conn, profile, flags):
    module = "sql.warehouses"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM warehouses ORDER BY name").fetchall()
        console.print(f"\n[bold]SQL Warehouses[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",      style="dim")
        t.add_column("Name",    style="cyan")
        t.add_column("Size")
        t.add_column("State")
        t.add_column("Creator")
        for r in rows:
            state = r["state"] or "?"
            sc = "green" if state == "RUNNING" else "yellow"
            t.add_row(r["warehouse_id"], r["name"] or "?",
                      r["cluster_size"] or "?",
                      f"[{sc}]{state}[/{sc}]",
                      r["creator"] or "?")
        console.print(t)
        return

    console.print("\n[bold]SQL Warehouses[/bold]\n")
    try:
        whs = list(w.warehouses.list())
        now = now_iso()
        t   = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",           style="dim")
        t.add_column("Name",         style="cyan")
        t.add_column("Size")
        t.add_column("State")
        t.add_column("Creator")
        for wh in whs:
            state = wh.state.value if wh.state else "?"
            sc    = "green" if state == "RUNNING" else "yellow"
            t.add_row(str(wh.id), wh.name or "?",
                      wh.cluster_size or "?",
                      f"[{sc}]{state}[/{sc}]",
                      wh.creator_name or "?")
            conn.execute(
                "INSERT OR REPLACE INTO warehouses VALUES (?,?,?,?,?,?)",
                (str(wh.id), wh.name, wh.cluster_size, state,
                 wh.creator_name, now)
            )
        log_pull(conn, module, profile, len(whs))
        conn.commit()
        console.print(t)
        next_step("sql execute --warehouse <id> --sql \"<query>\" --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_queries_list(w, conn, profile, flags):
    module = "sql.queries"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM saved_queries ORDER BY name").fetchall()
        console.print(f"\n[bold]Saved Queries[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",    style="dim")
        t.add_column("Name",  style="cyan")
        t.add_column("Owner")
        for r in rows:
            t.add_row(r["query_id"], r["name"] or r["query_id"], r["created_by"] or "?")
        console.print(t)
        return

    console.print("\n[bold]Saved Queries[/bold]\n")
    try:
        queries = list(w.queries.list())
        shown   = limit(queries, flags["limit"])
        now     = now_iso()
        t       = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",    style="dim")
        t.add_column("Name",  style="cyan")
        t.add_column("Owner")
        for q in shown:
            t.add_row(str(q.id), q.display_name or "?", q.owner_user_name or "?")
            conn.execute(
                "INSERT OR REPLACE INTO saved_queries VALUES (?,?,?,?,?)",
                (str(q.id), q.display_name, None, q.owner_user_name, now)
            )
        log_pull(conn, module, profile, len(queries))
        conn.commit()
        console.print(t)
        if flags["limit"] > 0 and len(queries) > flags["limit"]:
            console.print(f"[dim]  {len(queries)} total — showing {flags['limit']}[/dim]")
        next_step("sql queries-get --id <id> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_queries_get(w, conn, profile, flags):
    qid = flags.get("id")
    if not qid:
        qid = input("Query ID (from: sql queries --run): ").strip()
    console.print(f"\n[bold]Saved Query[/bold]  [dim]{qid}[/dim]\n")
    try:
        q   = w.queries.get(id=qid)
        now = now_iso()
        console.print(f"  Name    : [cyan]{q.display_name or '?'}[/cyan]")
        console.print(f"  Owner   : {q.owner_user_name or '?'}")
        if q.query_text:
            console.print("\n[bold]Query Text[/bold]")
            console.print(f"  {q.query_text}")
        conn.execute(
            "INSERT OR REPLACE INTO saved_queries VALUES (?,?,?,?,?)",
            (str(q.id), q.display_name, q.query_text, q.owner_user_name, now)
        )
        conn.commit()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_query_history(w, conn, profile, flags):
    console.print("\n[bold]Query History[/bold]\n")
    wh_id = flags.get("warehouse")
    if wh_id:
        console.print(f"  [dim]Filter: warehouse={wh_id}[/dim]\n")
    try:
        from databricks.sdk.service.sql import QueryFilter
        kwargs = {}
        if wh_id:
            kwargs["filter_by"] = QueryFilter(warehouse_ids=[wh_id])
        history = []
        page_token = None
        while True:
            if page_token:
                kwargs["page_token"] = page_token
            resp = w.query_history.list(**kwargs)
            history.extend(resp.res or [])
            if not resp.has_next_page or (flags["limit"] > 0 and len(history) >= flags["limit"]):
                break
            page_token = resp.next_page_token
        shown = limit(history, flags["limit"])

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("User",        style="cyan")
        t.add_column("Start Time")
        t.add_column("Duration",    justify="right")
        t.add_column("Status")
        t.add_column("Query Preview")
        for q in shown:
            start = fmt_epoch_ms(q.query_start_time_ms)
            dur   = f"{q.duration // 1000}s" if q.duration else "?"
            stat  = q.status.value if q.status else "?"
            sc    = "green" if stat == "FINISHED" else "yellow"
            preview = (q.query_text or "")[:60].replace("\n", " ")
            t.add_row(q.user_name or "?", start, dur,
                      f"[{sc}]{stat}[/{sc}]", preview)
        console.print(t)
        if flags["limit"] > 0 and len(history) > flags["limit"]:
            console.print(f"[dim]  showing {flags['limit']} — use --limit 0 for all[/dim]")
        next_step("sql execute --warehouse <id> --sql \"<query>\" --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_execute(w, conn, profile, flags):
    wh_id = flags.get("warehouse")
    if not wh_id:
        wh_id = input("Warehouse ID (from: sql warehouses --run): ").strip()
    sql = flags.get("sql")
    if not sql:
        sql = input("SQL: ").strip()

    console.print(f"\n[bold]Execute SQL[/bold]  [dim]warehouse={wh_id}[/dim]\n")
    console.print(f"  [dim]{sql}[/dim]\n")
    try:
        from databricks.sdk.service.sql import StatementState
        result = w.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=wh_id,
            wait_timeout="50s",
        )
        state = result.status.state.value if result.status and result.status.state else ""
        if state == "FAILED":
            msg = result.status.error.message if result.status and result.status.error else "unknown"
            console.print(f"[red]Failed: {msg}[/red]")
            return
        if state != "SUCCEEDED":
            console.print(f"[yellow]Query ended with state: {state}[/yellow]")
            return
        schema = result.manifest.schema.columns if result.manifest and result.manifest.schema else []
        cols   = [c.name for c in schema]
        rows   = result.result.data_array if result.result and result.result.data_array else []

        if cols:
            t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
            for c in cols:
                t.add_column(c, style="cyan")
            for row in rows[:500]:
                t.add_row(*[str(v) if v is not None else "" for v in row])
            console.print(t)
            if len(rows) > 500:
                console.print(f"[dim]  {len(rows)} rows — showing 500[/dim]")
        else:
            console.print("[dim](no results)[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "warehouses": {
        "description": "List SQL warehouses — ID, size, state, creator",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_warehouses,
    },
    "queries": {
        "description": "List saved queries (IDs and names)",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": [],
        "flags": [("--limit N", "Max results — default 100, 0=all")],
        "fn": run_queries_list,
    },
    "queries-get": {
        "description": "Get full saved query text by ID",
        "activity": ["cred", "info"], "type": "R", "noise": "Low",
        "prereqs": ["Query ID — from sql queries"],
        "caveats": ["Saved queries may contain hardcoded credentials in query text"],
        "flags": [("--id ID", "Query ID")],
        "required_flags": ["--id"],
        "fn": run_queries_get,
    },
    "query-history": {
        "description": "List recent query history with user, time, status, preview",
        "activity": ["info", "data"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["Server-side filter available for warehouse — client-side for time range"],
        "flags": [
            ("--warehouse ID", "Filter by warehouse ID (server-side)"),
            ("--limit N",      "Max results — default 100, 0=all"),
        ],
        "fn": run_query_history,
    },
    "execute": {
        "description": "Run a SQL statement against a warehouse (runs as current token identity)",
        "activity": ["data"], "type": "R", "noise": "Low-Medium",
        "prereqs": ["Running warehouse ID — from sql warehouses"],
        "caveats": [
            "Runs under current token's identity — check permissions first",
            "Warehouse must be in RUNNING state",
        ],
        "flags": [
            ("--warehouse ID", "Warehouse ID"),
            ("--sql TEXT",     "SQL statement (prompts if omitted)"),
        ],
        "required_flags": ["--warehouse"],
        "fn": run_execute,
    },
}
