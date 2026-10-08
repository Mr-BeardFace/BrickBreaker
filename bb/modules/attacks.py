"""Attacks module — offensive simulation scenarios"""

import urllib.request

from bb.core.display import console, next_step
from bb.core.sql_exec import exec_sql
from rich import box
from rich.table import Table


def run_smash_grab(w, conn, profile, flags):
    if not flags.get("aggressive"):
        console.print("[yellow]EXEC operation — requires --aggressive flag[/yellow]")
        console.print("  [dim]Submits SELECT * on every accessible table. All queries visible in audit log.[/dim]")
        return

    warehouse = flags.get("warehouse")
    if not warehouse:
        console.print("[red]--warehouse <id> required[/red]")
        next_step("sql warehouses --run")
        return

    catalog_filter   = flags.get("catalog")
    schema_filter    = flags.get("schema")
    exclude_catalogs = set((flags.get("exclude_catalog") or "").split(",")) - {""}
    exclude_schemas  = set((flags.get("exclude_schema") or "").split(",")) - {""}

    from databricks.sdk.service.sql import Disposition

    console.print(f"\n[bold]Smash & Grab[/bold]  [dim][simulate] warehouse={warehouse}[/dim]\n")
    if catalog_filter:
        console.print(f"  [dim]Scope: catalog={catalog_filter}[/dim]")
    if schema_filter:
        console.print(f"  [dim]Scope: schema={schema_filter}[/dim]")
    if exclude_catalogs:
        console.print(f"  [dim]Exclude catalogs: {', '.join(sorted(exclude_catalogs))}[/dim]")
    if exclude_schemas:
        console.print(f"  [dim]Exclude schemas: {', '.join(sorted(exclude_schemas))}[/dim]")
    console.print()

    total_rows = 0
    tables_ok  = 0
    tables_err = 0

    try:
        catalogs = list(w.catalogs.list())
    except Exception as e:
        console.print(f"[red]Cannot list catalogs: {e}[/red]")
        return

    if catalog_filter:
        catalogs = [c for c in catalogs if c.name == catalog_filter]
    if exclude_catalogs:
        catalogs = [c for c in catalogs if c.name not in exclude_catalogs]

    for cat in catalogs:
        try:
            schemas = list(w.schemas.list(catalog_name=cat.name))
        except Exception:
            continue
        if schema_filter:
            schemas = [s for s in schemas if s.name == schema_filter]
        if exclude_schemas:
            schemas = [s for s in schemas if s.name not in exclude_schemas]

        for schema in schemas:
            try:
                tables = list(w.tables.list(catalog_name=cat.name, schema_name=schema.name))
            except Exception:
                continue

            for tbl in tables:
                full = tbl.full_name or f"{cat.name}.{schema.name}.{tbl.name}"
                try:
                    r     = exec_sql(w, f"SELECT * FROM {full}", warehouse,
                                     disposition=Disposition.EXTERNAL_LINKS)
                    state = r.status.state.value if r.status and r.status.state else ""
                    if state == "SUCCEEDED":
                        row_count = getattr(r.manifest, "total_row_count", None) if r.manifest else None
                        links     = (getattr(r.result, "external_links", None) or []) if r.result else []
                        n_chunks  = len(links)
                        if row_count:
                            total_rows += row_count
                        tables_ok += 1
                        rc_str = f"{row_count:,}" if row_count is not None else "?"
                        # Range GET on first chunk — 1 byte, proves S3 access in CloudTrail
                        s3_str = "[dim]inline[/dim]"
                        if links:
                            try:
                                req = urllib.request.Request(links[0].external_link)
                                req.add_header("Range", "bytes=0-0")
                                with urllib.request.urlopen(req) as resp:
                                    resp.read()
                                    s3_str = f"[green]S3 {resp.status}[/green] [dim]({n_chunks} chunks)[/dim]"
                            except Exception as ex:
                                s3_str = f"[red]S3 error: {ex}[/red]"
                        console.print(f"  [green]✓[/green] [cyan]{full}[/cyan]  {rc_str} rows  {s3_str}")
                    else:
                        tables_err += 1
                        console.print(f"  [yellow]–[/yellow] [dim]{full}[/dim]  {state.lower()}")
                except Exception as e:
                    err = str(e)
                    tables_err += 1
                    if "PERMISSION_DENIED" in err or "permission" in err.lower():
                        console.print(f"  [dim]✗ {full}  denied[/dim]")
                    else:
                        console.print(f"  [red]✗[/red] [dim]{full}[/dim]  {err[:80]}")

    console.print(f"\n[bold]Summary[/bold]\n")
    t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    t.add_column("", style="dim", min_width=24)
    t.add_column("")
    t.add_row("Tables accessible",     f"[green]{tables_ok}[/green]")
    t.add_row("Tables denied/error",   f"[yellow]{tables_err}[/yellow]" if tables_err else "0")
    t.add_row("Total rows (simulated)", f"[yellow]{total_rows:,}[/yellow]")
    console.print(t)
    next_step("loot dump --run")


COMMANDS = {
    "smash-grab": {
        "description": "Simulate full-workspace data exfil — SELECT * every table, no data pulled",
        "activity": ["data"], "type": "R", "noise": "High — one SQL statement per table",
        "prereqs": ["Warehouse ID — from sql warehouses"],
        "caveats": [
            "Uses EXTERNAL_LINKS disposition — row data never enters memory",
            "Range GET (bytes=0-0) on first S3 chunk per table — logged in CloudTrail as GetObject",
            "All queries visible in warehouse query history and Databricks audit log",
            "Use --catalog / --schema to narrow scope",
        ],
        "flags": [
            ("--warehouse ID",        "Warehouse to run queries against"),
            ("--catalog NAME",        "Limit to one catalog (optional)"),
            ("--schema NAME",         "Limit to one schema within --catalog (optional)"),
            ("--exclude-catalog CSV", "Comma-separated catalog names to skip"),
            ("--exclude-schema CSV",  "Comma-separated schema names to skip"),
        ],
        "required_flags": ["--warehouse"],
        "aggressive": [
            "Submits SELECT * per accessible table across all catalogs",
            "Every query visible in warehouse history and audit logs",
        ],
        "fn": run_smash_grab,
    },
}
