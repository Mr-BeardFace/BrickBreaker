"""Unity Catalog module — catalogs, schemas, tables, connections, credentials, grants"""

import json

from bb.core.db import now_iso, log_pull, should_use_cache
from bb.core.display import console, next_step
from bb.core.flags import limit
from rich import box
from rich.table import Table


def run_catalogs(w, conn, profile, flags):
    module = "uc.catalogs"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM uc_catalogs ORDER BY name").fetchall()
        console.print(f"\n[bold]Catalogs[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",    style="cyan")
        t.add_column("Owner")
        t.add_column("Comment")
        for r in rows:
            t.add_row(r["name"], r["owner"] or "?", r["comment"] or "")
        console.print(t)
        next_step("uc schemas --catalog <name> --run")
        return

    console.print("\n[bold]Catalogs[/bold]\n")
    try:
        cats  = list(w.catalogs.list())
        now   = now_iso()
        t     = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",    style="cyan")
        t.add_column("Owner")
        t.add_column("Comment")
        for c in cats:
            t.add_row(c.name or "?", c.owner or "?", c.comment or "")
            conn.execute(
                "INSERT OR REPLACE INTO uc_catalogs VALUES (?,?,?,?)",
                (c.name, c.owner, c.comment, now)
            )
        log_pull(conn, module, profile, len(cats))
        conn.commit()
        console.print(t)
        next_step("uc schemas --catalog <name> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_schemas(w, conn, profile, flags):
    catalog = flags.get("catalog")
    if not catalog:
        catalog = input("Catalog name (from: uc catalogs --run)  e.g. main: ").strip()
    module = f"uc.schemas:{catalog}"
    console.print(f"\n[bold]Schemas[/bold]  [dim]{catalog}[/dim]\n")
    try:
        schemas = list(w.schemas.list(catalog_name=catalog))
        now     = now_iso()
        t       = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Full Name",   style="cyan")
        t.add_column("Owner")
        for s in schemas:
            t.add_row(s.full_name or "?", s.owner or "?")
            conn.execute(
                "INSERT OR REPLACE INTO uc_schemas VALUES (?,?,?,?,?)",
                (s.full_name, catalog, s.name, s.owner, now)
            )
        log_pull(conn, module, profile, len(schemas))
        conn.commit()
        console.print(t)
        next_step(f"uc tables --catalog {catalog} --schema <name> --run",
                  f"uc grants --id {catalog}.<schema> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_tables(w, conn, profile, flags):
    catalog     = flags.get("catalog")
    schema_name = flags.get("schema")
    if not catalog:
        catalog = input("Catalog name (from: uc catalogs --run)  e.g. main: ").strip()
    if not schema_name:
        schema_name = input("Schema name (from: uc schemas --catalog <name> --run)  e.g. default: ").strip()
    module = f"uc.tables:{catalog}.{schema_name}"
    console.print(f"\n[bold]Tables[/bold]  [dim]{catalog}.{schema_name}[/dim]\n")
    try:
        tables = list(w.tables.list(catalog_name=catalog, schema_name=schema_name))
        shown  = limit(tables, flags["limit"])
        now    = now_iso()
        t      = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Full Name",   style="cyan")
        t.add_column("Type")
        t.add_column("Data Source")
        for tbl in shown:
            ds = tbl.storage_location or ""
            t.add_row(tbl.full_name or "?",
                      tbl.table_type.value if tbl.table_type else "?", ds[:60])
            conn.execute(
                "INSERT OR REPLACE INTO uc_tables VALUES (?,?,?,?,?,?,?)",
                (tbl.full_name, catalog, schema_name, tbl.name,
                 tbl.table_type.value if tbl.table_type else "?", ds, now)
            )
        log_pull(conn, module, profile, len(tables))
        conn.commit()
        console.print(t)
        if flags["limit"] > 0 and len(tables) > flags["limit"]:
            console.print(f"[dim]  {len(tables)} total — showing {flags['limit']}[/dim]")
        next_step(f"uc temp-table-creds --id <catalog.schema.table> --run",
                  f"uc grants --id <full_name> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_external_locations(w, conn, profile, flags):
    module = "uc.external-locations"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    def _print_locs(records):
        for rec in records:
            t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
            t.add_column("", style="dim",   min_width=12)
            t.add_column("", style="white")
            t.add_row("Name",       f"[cyan]{rec[0]}[/cyan]")
            t.add_row("URL",        f"[yellow]{rec[1] or '?'}[/yellow]")
            t.add_row("Credential", rec[2] or "?")
            console.print(t)

    if use_cache:
        rows = conn.execute("SELECT * FROM uc_external_locations ORDER BY name").fetchall()
        console.print(f"\n[bold]External Locations[/bold]  [dim](cached {age})[/dim]\n")
        _print_locs([(r["name"], r["url"], r["credential"]) for r in rows])
        next_step("uc temp-path-creds --path <url> --run")
        return

    console.print("\n[bold]External Locations[/bold]\n")
    try:
        locs = list(w.external_locations.list())
        now  = now_iso()
        for loc in locs:
            conn.execute(
                "INSERT OR REPLACE INTO uc_external_locations VALUES (?,?,?,?)",
                (loc.name, loc.url, loc.credential_name, now)
            )
        log_pull(conn, module, profile, len(locs))
        conn.commit()
        _print_locs([(loc.name, loc.url, loc.credential_name) for loc in locs])
        next_step("uc temp-path-creds --path <url> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_storage_credentials(w, conn, profile, flags):
    module = "uc.storage-credentials"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM uc_storage_credentials ORDER BY name").fetchall()
        console.print(f"\n[bold]Storage Credentials[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",      style="cyan")
        t.add_column("AWS ARN",   style="yellow")
        t.add_column("Azure Dir")
        for r in rows:
            t.add_row(r["name"], r["aws_arn"] or "", r["az_dir_id"] or "")
        console.print(t)
        next_step("uc external-locations --run",
                  "uc temp-path-creds --path <url> --run")
        return

    console.print("\n[bold]Storage Credentials[/bold]\n")
    try:
        creds = list(w.storage_credentials.list())
        now   = now_iso()
        t     = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",       style="cyan")
        t.add_column("AWS ARN",    style="yellow")
        t.add_column("Azure Dir")
        for c in creds:
            aws_arn = c.aws_iam_role.role_arn if c.aws_iam_role else ""
            az_dir  = c.azure_service_principal.directory_id \
                      if c.azure_service_principal else ""
            t.add_row(c.name or "?", aws_arn or "", az_dir or "")
            conn.execute(
                "INSERT OR REPLACE INTO uc_storage_credentials VALUES (?,?,?,?)",
                (c.name, aws_arn, az_dir, now)
            )
        log_pull(conn, module, profile, len(creds))
        conn.commit()
        console.print(t)
        next_step("uc external-locations --run",
                  "uc temp-path-creds --path <url> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_connections_list(w, conn, profile, flags):
    module = "uc.connections"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM uc_connections ORDER BY name").fetchall()
        console.print(f"\n[bold]Connections[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",            style="cyan")
        t.add_column("Connection Type")
        t.add_column("Has Options")
        for r in rows:
            has_opts = "[yellow]Yes[/yellow]" if r["options_json"] and r["options_json"] != "null" else ""
            t.add_row(r["name"], r["connection_type"] or "?", has_opts)
        console.print(t)
        next_step("uc connections-get --name <name> --run")
        return

    console.print("\n[bold]Connections[/bold]  [dim](names and types only — use connections-get for creds)[/dim]\n")
    try:
        conns = list(w.connections.list())
        now   = now_iso()
        t     = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",            style="cyan")
        t.add_column("Connection Type")
        t.add_column("Owner")
        for c in conns:
            ct = c.connection_type.value if c.connection_type else "?"
            t.add_row(c.name or "?", ct, c.owner or "?")
            conn.execute(
                "INSERT OR REPLACE INTO uc_connections VALUES (?,?,?,?)",
                (c.name, ct, None, now)
            )
        log_pull(conn, module, profile, len(conns))
        conn.commit()
        console.print(t)
        next_step("uc connections-get --name <name> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_connections_get(w, conn, profile, flags):
    name = flags.get("name") or flags.get("id")
    if not name:
        name = input("Connection name (from: uc connections --run)  e.g. my-snowflake-conn: ").strip()
    console.print(f"\n[bold]Connection[/bold]  [dim]{name}[/dim]\n")
    try:
        c   = w.connections.get(name=name)
        now = now_iso()
        ct  = c.connection_type.value if c.connection_type else "?"
        console.print(f"  Type   : {ct}")
        console.print(f"  Owner  : {c.owner or '?'}")
        options = c.options or {}
        if options:
            console.print("\n  [bold]Options[/bold]  [yellow](may contain credentials)[/yellow]")
            for k, v in options.items():
                console.print(f"    [cyan]{k}[/cyan] = {v}")
        else:
            console.print("  [dim]options: (empty)[/dim]")
        conn.execute(
            "INSERT OR REPLACE INTO uc_connections VALUES (?,?,?,?)",
            (c.name, ct, json.dumps(options), now)
        )
        conn.commit()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_connections_all(w, conn, profile, flags):
    module = "uc.connections-all"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute(
            "SELECT * FROM uc_connections WHERE options_json IS NOT NULL ORDER BY name"
        ).fetchall()
        console.print(f"\n[bold]All Connections (full options)[/bold]  [dim](cached {age})[/dim]\n")
        for r in rows:
            console.print(f"[cyan]{r['name']}[/cyan]  [dim]{r['connection_type'] or '?'}[/dim]")
            try:
                opts = json.loads(r["options_json"] or "{}")
                for k, v in opts.items():
                    console.print(f"  [cyan]{k}[/cyan] = {v}")
            except Exception:
                pass
        next_step("uc connections-get --name <name> --run")
        return

    console.print("\n[bold]All Connections (full options)[/bold]  [yellow]may contain credentials[/yellow]\n")
    try:
        conns = list(w.connections.list())
        now   = now_iso()
        for c in conns:
            ct = c.connection_type.value if c.connection_type else "?"
            try:
                full    = w.connections.get(name=c.name)
                options = full.options or {}
            except Exception:
                options = {}
            console.print(f"[cyan]{c.name}[/cyan]  [dim]{ct}[/dim]")
            for k, v in options.items():
                console.print(f"  [cyan]{k}[/cyan] = {v}")
            conn.execute(
                "INSERT OR REPLACE INTO uc_connections VALUES (?,?,?,?)",
                (c.name, ct, json.dumps(options), now)
            )
        log_pull(conn, module, profile, len(conns))
        conn.commit()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_grants(w, conn, profile, flags):
    """Two modes: --id <object> for grants on an object, --name <principal> for grants to a principal"""
    obj       = flags.get("id")
    principal = flags.get("name")

    if obj:
        console.print(f"\n[bold]Grants on[/bold] [cyan]{obj}[/cyan]\n")
        console.print("[yellow]ⓘ Object grants require specifying type — use securable_type parameter[/yellow]")
        console.print("[dim]  Direct API: w.grants.get(securable_type=..., full_name=...)[/dim]")
        console.print("[dim]  Types: catalog, schema, table, external_location, storage_credential[/dim]")
        # Attempt as catalog first, fall through
        try:
            for stype in ["catalog", "schema", "table", "external_location", "storage_credential"]:
                try:
                    result = w.grants.get(securable_type=stype, full_name=obj)
                    if result.privilege_assignments:
                        console.print(f"\n  [dim]Found as {stype}[/dim]")
                        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
                        t.add_column("Principal", style="cyan")
                        t.add_column("Privileges")
                        for pa in result.privilege_assignments:
                            privs = ", ".join(
                                (p.value if hasattr(p, "value") else str(p))
                                for p in (pa.privileges or [])
                            )
                            t.add_row(pa.principal or "?", privs)
                        console.print(t)
                        return
                except Exception:
                    continue
            console.print("[yellow]No grants found for that object[/yellow]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    elif principal:
        # R* — pull everything and filter locally
        console.print(f"\n[bold]Grants to principal[/bold] [cyan]{principal}[/cyan]  "
                      "[yellow]R* — pulls all objects locally[/yellow]\n")
        try:
            found = 0
            for cat in w.catalogs.list():
                try:
                    g = w.grants.get(securable_type="catalog", full_name=cat.name)
                    for pa in (g.privilege_assignments or []):
                        if pa.principal == principal:
                            privs = ", ".join(
                                (p.value if hasattr(p, "value") else str(p))
                                for p in (pa.privileges or [])
                            )
                            console.print(f"  [cyan]catalog:{cat.name}[/cyan]  {privs}")
                            found += 1
                except Exception:
                    pass
            if found == 0:
                console.print("[dim]No catalog-level grants found for that principal[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    else:
        console.print("[red]Provide --id <object_name> or --name <principal>[/red]\n")
        console.print("  [dim]--id   <object_name>   grants ON an object  (catalog, schema, table, external location)[/dim]")
        console.print("  [dim]                       retrieve object names from:[/dim]")
        console.print("  [dim]                         uc catalogs --run            → catalog names[/dim]")
        console.print("  [dim]                         uc schemas --catalog <n> --run  → schema names[/dim]")
        console.print("  [dim]                         uc tables --catalog <n> --schema <n> --run  → table full names[/dim]")
        console.print("  [dim]                         uc external-locations --run  → external location names[/dim]")
        console.print("  [dim]--name <principal>     grants TO a user/group/SP  (R* — scans all catalogs)[/dim]")
        console.print("  [dim]                       retrieve principals from:[/dim]")
        console.print("  [dim]                         identity users --run         → user emails[/dim]")
        console.print("  [dim]                         identity groups --run        → group display names[/dim]")
        console.print("  [dim]                         identity service-principals --run  → SP display names[/dim]")


def run_metastore(w, conn, profile, flags):
    console.print("\n[bold]Metastore Info[/bold]\n")
    try:
        m = w.metastores.summary()
        t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        t.add_column("Field", style="dim", min_width=24)
        t.add_column("Value")
        t.add_row("Name",           m.name or "?")
        t.add_row("Metastore ID",   m.metastore_id or "?")
        t.add_row("Owner",          m.owner or "?")
        t.add_row("Cloud",          m.cloud or "?")
        t.add_row("Region",         m.region or "?")
        t.add_row("Storage Root",   m.storage_root or "?")
        t.add_row("Delta Sharing",  m.delta_sharing_scope.value if getattr(m, "delta_sharing_scope", None) else "?")
        console.print(t)
        next_step("uc catalogs --run",
                  "uc external-locations --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_volumes(w, conn, profile, flags):
    catalog     = flags.get("catalog")
    schema_name = flags.get("schema")
    if not catalog:
        catalog = input("Catalog name (from: uc catalogs --run)  e.g. main: ").strip()
    if not schema_name:
        schema_name = input("Schema name (from: uc schemas --catalog <name> --run)  e.g. default: ").strip()
    console.print(f"\n[bold]Volumes[/bold]  [dim]{catalog}.{schema_name}[/dim]\n")
    try:
        vols = list(w.volumes.list(catalog_name=catalog, schema_name=schema_name))
        t    = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Full Name",     style="cyan")
        t.add_column("Volume Type")
        t.add_column("Storage Location")
        for v in vols:
            t.add_row(v.full_name or "?",
                      v.volume_type.value if v.volume_type else "?",
                      v.storage_location or "")
        console.print(t)
        next_step("uc temp-path-creds --path <storage_location> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def _pick_warehouse(w) -> str | None:
    """Prompt user to pick from running warehouses. Returns ID or None."""
    try:
        running = [wh for wh in w.warehouses.list()
                   if (wh.state.value if wh.state else "") == "RUNNING"]
    except Exception:
        return None
    if not running:
        console.print("  [yellow]No running warehouses found — skipping row counts[/yellow]")
        return None
    console.print("\n  [bold]Select warehouse for row counts[/bold]")
    for i, wh in enumerate(running):
        console.print(f"  [{i+1}] {wh.name or '?'}  [dim]{wh.cluster_size or ''}  {wh.id}[/dim]")
    raw = input(f"  Choice [1-{len(running)}] or Enter to skip: ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(running):
        return str(running[int(raw) - 1].id)
    return None


def _auto_warehouse(w, hint: str | None = None) -> tuple[str | None, str]:
    """
    Return (warehouse_id, source_label) for the best running warehouse.
    If hint (catalog.schema or table name) is given, checks query history first.
    Returns (None, "") when multiple warehouses exist and none match history.
    """
    try:
        running = [wh for wh in w.warehouses.list()
                   if (wh.state.value if wh.state else "") == "RUNNING"]
    except Exception:
        return None, ""

    if not running:
        return None, ""
    if len(running) == 1:
        return str(running[0].id), f"auto ({running[0].name or running[0].id})"

    # Multiple warehouses — check query history for the hint
    if hint:
        try:
            from collections import Counter
            resp   = w.query_history.list()
            counts = Counter()
            hint_l = hint.lower()
            running_ids = {str(wh.id): wh.name or str(wh.id) for wh in running}
            for q in (resp.res or []):
                if hint_l in (q.query_text or "").lower() and q.warehouse_id in running_ids:
                    counts[q.warehouse_id] += 1
            if counts:
                best_id = counts.most_common(1)[0][0]
                return best_id, f"history match ({running_ids[best_id]}, {counts[best_id]} queries)"
        except Exception:
            pass

    return None, ""


def run_table_meta(w, conn, profile, flags):
    full_name = flags.get("id") or flags.get("name")
    warehouse = flags.get("warehouse")

    if not full_name:
        full_name = input("Table full name (from: uc tables --catalog <n> --schema <n> --run)  e.g. main.default.my_table: ").strip()

    if not warehouse:
        warehouse, source = _auto_warehouse(w, hint=full_name)
        if warehouse:
            console.print(f"\n  [dim]Warehouse: {warehouse}  [{source}][/dim]")
        else:
            warehouse = _pick_warehouse(w)

    console.print(f"\n[bold]Table Metadata[/bold]  [dim]{full_name}[/dim]\n")
    try:
        tbl = w.tables.get(full_name=full_name)
        console.print(f"  Type    : {tbl.table_type.value if tbl.table_type else '?'}")
        console.print(f"  Owner   : {tbl.owner or '?'}")
        if tbl.storage_location:
            console.print(f"  Storage : [yellow]{tbl.storage_location}[/yellow]")

        cols = tbl.columns or []
        if cols:
            console.print(f"\n[bold]Columns[/bold]  [dim]({len(cols)})[/dim]\n")
            t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
            t.add_column("Name",    style="cyan")
            t.add_column("Type")
            t.add_column("Nullable")
            t.add_column("Comment", style="dim")
            for col in cols:
                type_name = col.type_name.value if hasattr(col.type_name, "value") else str(col.type_name or "?")
                nullable  = "" if col.nullable else "[dim]NOT NULL[/dim]"
                t.add_row(col.name or "?", type_name, nullable, col.comment or "")
            console.print(t)
        else:
            console.print("[dim]No column metadata[/dim]")

        # Cached row count from Delta table properties (no warehouse needed)
        props = tbl.properties or {}
        cached_rows = props.get("delta.numRecords") or props.get("numRows")
        if cached_rows is not None:
            console.print(f"\n  Row Count  : [yellow]{cached_rows}[/yellow]  [dim](cached — from last OPTIMIZE/ANALYZE)[/dim]")

        if warehouse:
            try:
                r = w.statement_execution.execute_statement(
                    statement=f"SELECT COUNT(*) FROM {full_name}",
                    warehouse_id=warehouse,
                    wait_timeout="50s",
                )
                state = r.status.state.value if r.status and r.status.state else ""
                if state == "SUCCEEDED" and r.result and r.result.data_array:
                    console.print(f"  Live Count : [yellow]{r.result.data_array[0][0]}[/yellow]")
                elif state not in ("SUCCEEDED", ""):
                    console.print(f"  [yellow]Row count query {state.lower()}[/yellow]")
            except Exception as e:
                console.print(f"  [red]Row count error: {e}[/red]")

        n_rows = flags.get("rows")
        if warehouse and n_rows:
            console.print(f"\n[bold]Sample Rows[/bold]  [dim](LIMIT {n_rows})[/dim]\n")
            try:
                r = w.statement_execution.execute_statement(
                    statement=f"SELECT * FROM {full_name} LIMIT {n_rows}",
                    warehouse_id=warehouse,
                    wait_timeout="50s",
                )
                state     = r.status.state.value if r.status and r.status.state else ""
                schema    = r.manifest.schema.columns if r.manifest and r.manifest.schema else []
                col_names = [c.name for c in schema]
                rows      = r.result.data_array if state == "SUCCEEDED" and r.result and r.result.data_array else []
                if col_names:
                    t2 = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
                    for cn in col_names:
                        t2.add_column(cn, style="cyan")
                    for row in rows:
                        t2.add_row(*[str(v) if v is not None else "" for v in row])
                    console.print(t2)
                else:
                    console.print("[dim](no rows)[/dim]")
            except Exception as e:
                console.print(f"  [red]Sample error: {e}[/red]")
        elif n_rows and not warehouse:
            console.print("\n  [dim]--rows requires a warehouse — add --warehouse <id>[/dim]")

        if cached_rows is None and not warehouse:
            console.print("\n  [dim]Row count unavailable — add --warehouse <id> for live count[/dim]")
            next_step(f"uc table-meta --id {full_name} --warehouse <id> --run",
                      f"uc table-meta --id {full_name} --warehouse <id> --rows 10 --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_schema_meta(w, conn, profile, flags):
    catalog     = flags.get("catalog")
    schema_name = flags.get("schema")
    warehouse   = flags.get("warehouse")

    if not catalog:
        catalog = input("Catalog name (from: uc catalogs --run)  e.g. main: ").strip()
    if not schema_name:
        schema_name = input("Schema name (from: uc schemas --catalog <n> --run)  e.g. default: ").strip()

    if not warehouse:
        warehouse, source = _auto_warehouse(w, hint=f"{catalog}.{schema_name}")
        if warehouse:
            console.print(f"\n  [dim]Warehouse: {warehouse}  [{source}][/dim]")
        else:
            warehouse = _pick_warehouse(w)

    console.print(f"\n[bold]Schema Metadata[/bold]  [dim]{catalog}.{schema_name}[/dim]\n")
    if warehouse:
        console.print(f"  [dim]Row counts via warehouse {warehouse} — may be slow[/dim]\n")
    try:
        tables = list(w.tables.list(catalog_name=catalog, schema_name=schema_name))

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Table",     style="cyan")
        t.add_column("Type")
        t.add_column("Columns",   justify="right")
        t.add_column("Rows",      justify="right", style="yellow")

        for tbl in tables:
            try:
                full      = w.tables.get(full_name=tbl.full_name)
                col_cnt   = str(len(full.columns or []))
                props     = full.properties or {}
                row_count = props.get("delta.numRecords") or props.get("numRows")
                row_str   = str(row_count) + " [dim]*[/dim]" if row_count is not None else ""
            except Exception:
                col_cnt, row_str = "?", ""
            ttype = tbl.table_type.value if tbl.table_type else "?"
            if warehouse:
                try:
                    r = w.statement_execution.execute_statement(
                        statement=f"SELECT COUNT(*) FROM {tbl.full_name}",
                        warehouse_id=warehouse,
                        wait_timeout="50s",
                    )
                    state   = r.status.state.value if r.status and r.status.state else ""
                    row_str = str(r.result.data_array[0][0]) if state == "SUCCEEDED" and r.result and r.result.data_array else "?"
                except Exception:
                    row_str = "[red]error[/red]"
            t.add_row(tbl.name or "?", ttype, col_cnt, row_str)

        console.print(t)
        console.print(f"\n  [dim]{len(tables)} table(s)[/dim]")

        if not warehouse:
            console.print("  [dim]* cached row count from Delta stats — add --warehouse <id> for live counts[/dim]")
            next_step(
                f"uc schema-meta --catalog {catalog} --schema {schema_name} --warehouse <id> --run",
                f"uc table-meta --id {catalog}.{schema_name}.<table> --run",
            )
        else:
            next_step(
                f"uc table-meta --id {catalog}.{schema_name}.<table> --warehouse {warehouse} --run",
                f"uc temp-table-creds --id {catalog}.{schema_name}.<table> --run",
            )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_temp_path_creds(w, conn, profile, flags):
    url = flags.get("path") or flags.get("id")
    if not url:
        url = input("External location URL (from: uc external-locations --run)  e.g. s3://my-bucket/path/ or abfss://container@account.dfs.core.windows.net/path/: ").strip()
    console.print(f"\n[bold]Temporary Path Credentials[/bold]  [dim]{url}[/dim]\n")
    console.print("[yellow]ⓘ R-only API — no cluster required[/yellow]\n")
    try:
        from databricks.sdk.service.catalog import PathOperation
        creds = w.temporary_path_credentials.generate_temporary_path_credentials(url=url, operation=PathOperation.PATH_READ)
        if hasattr(creds, "aws_temp_credentials") and creds.aws_temp_credentials:
            a = creds.aws_temp_credentials
            console.print("[bold]AWS STS Credentials[/bold]")
            console.print(f"  AccessKeyId     : [yellow]{a.access_key_id}[/yellow]")
            console.print(f"  SecretAccessKey : [yellow]{a.secret_access_key}[/yellow]")
            console.print(f"  SessionToken    : [yellow]{a.session_token}[/yellow]")
        elif getattr(creds, "azure_user_delegation_sas", None):
            console.print("[bold]Azure SAS Token[/bold]")
            console.print(f"  [yellow]{creds.azure_user_delegation_sas.sas_token}[/yellow]")
        elif getattr(creds, "azure_aad", None):
            console.print("[bold]Azure AAD Token[/bold]")
            console.print(f"  [yellow]{creds.azure_aad}[/yellow]")
        else:
            console.print(repr(creds))
    except Exception as e:
        err = str(e)
        if "EXTERNAL USE LOCATION" in err or "does not have" in err.lower():
            console.print(f"[yellow]Permission denied[/yellow]: {err}")
            console.print("\n  [dim]EXTERNAL USE LOCATION is a UC privilege on the external location.[/dim]")
            console.print("  [dim]Current identity lacks it — check grants with:[/dim]")
            next_step("uc grants --id <external_location_name> --run",
                      "uc external-locations --run")
        else:
            console.print(f"[red]Error: {e}[/red]")


def run_temp_table_creds(w, conn, profile, flags):
    table_id = flags.get("id") or flags.get("name")
    if not table_id:
        table_id = input("Table full name (from: uc tables --catalog <n> --schema <n> --run)  e.g. main.default.my_table: ").strip()
    console.print(f"\n[bold]Temporary Table Credentials[/bold]  [dim]{table_id}[/dim]\n")
    console.print("[yellow]ⓘ Direct storage creds — bypasses Databricks audit logging[/yellow]\n")
    try:
        from databricks.sdk.service.catalog import TableOperation
        creds = w.temporary_table_credentials.generate_temporary_table_credentials(
            table_id=table_id, operation=TableOperation.READ
        )
        if hasattr(creds, "aws_temp_credentials") and creds.aws_temp_credentials:
            a = creds.aws_temp_credentials
            console.print("[bold]AWS STS Credentials[/bold]")
            console.print(f"  AccessKeyId     : [yellow]{a.access_key_id}[/yellow]")
            console.print(f"  SecretAccessKey : [yellow]{a.secret_access_key}[/yellow]")
            console.print(f"  SessionToken    : [yellow]{a.session_token}[/yellow]")
        elif getattr(creds, "azure_user_delegation_sas", None):
            console.print("[bold]Azure SAS Token[/bold]")
            console.print(f"  [yellow]{creds.azure_user_delegation_sas.sas_token}[/yellow]")
        elif getattr(creds, "azure_aad", None):
            console.print("[bold]Azure AAD Token[/bold]")
            console.print(f"  [yellow]{creds.azure_aad}[/yellow]")
        else:
            console.print(repr(creds))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "catalogs": {
        "description": "List all Unity Catalog catalogs",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_catalogs,
    },
    "schemas": {
        "description": "List schemas in a catalog",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": ["Catalog name"],
        "caveats": [],
        "flags": [("--catalog NAME", "Catalog name")],
        "required_flags": ["--catalog"],
        "fn": run_schemas,
    },
    "tables": {
        "description": "List tables in a schema — name, type, storage location",
        "activity": ["info", "data"], "type": "R", "noise": "Low",
        "prereqs": ["Catalog name", "Schema name"],
        "caveats": [],
        "flags": [
            ("--catalog NAME", "Catalog name"),
            ("--schema NAME",  "Schema name"),
            ("--limit N",      "Max results — default 100, 0=all"),
        ],
        "required_flags": ["--catalog", "--schema"],
        "fn": run_tables,
    },
    "external-locations": {
        "description": "List external storage locations and their credential bindings",
        "activity": ["latm", "cred"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["Use temp-path-creds to get actual STS/SAS tokens for these locations"],
        "flags": [],
        "fn": run_external_locations,
    },
    "storage-credentials": {
        "description": "List storage credential objects (IAM roles / service principals)",
        "activity": ["latm"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_storage_credentials,
    },
    "connections": {
        "description": "List connection names and types (no credential values)",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_connections_list,
    },
    "connections-get": {
        "description": "Get full connection config for one connection (options may include credentials)",
        "activity": ["cred"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["options dict may contain personalAccessToken, host, httpPath — needs live test to confirm"],
        "flags": [("--name NAME", "Connection name"), ("--id NAME", "Alias for --name")],
        "required_flags": ["--name"],
        "fn": run_connections_get,
    },
    "connections-all": {
        "description": "Get full options for every connection in one pass",
        "activity": ["cred"], "type": "R", "noise": "Medium — one get() per connection",
        "prereqs": [],
        "caveats": ["options dict may contain credentials — needs live test to confirm"],
        "flags": [],
        "fn": run_connections_all,
    },
    "grants": {
        "description": "Show grants on an object or for a principal",
        "activity": ["info"], "type": "R",
        "noise": "Low for --id / R* Medium for --name (pulls all objects client-side)",
        "prereqs": [],
        "caveats": ["--name <principal> is R* — iterates all catalogs locally"],
        "flags": [
            ("--id OBJECT",     "Object full name — returns all grants on it"),
            ("--name PRINCIPAL", "Principal name — returns all objects they have access to (R*)"),
        ],
        "fn": run_grants,
    },
    "metastore": {
        "description": "Current metastore info — ID, cloud, region, storage root",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_metastore,
    },
    "volumes": {
        "description": "List volumes in a schema",
        "activity": ["info", "data"], "type": "R", "noise": "Low",
        "prereqs": ["Catalog name", "Schema name"],
        "caveats": [],
        "flags": [
            ("--catalog NAME", "Catalog name"),
            ("--schema NAME",  "Schema name"),
        ],
        "required_flags": ["--catalog", "--schema"],
        "fn": run_volumes,
    },
    "table-meta": {
        "description": "Columns, row count, and sample rows for a table",
        "activity": ["info", "data"], "type": "R", "noise": "Low — get() only; Medium with --warehouse",
        "prereqs": ["Table full name (catalog.schema.table)"],
        "caveats": [
            "Columns from API — no warehouse needed",
            "Row count and samples require --warehouse (auto-detected from query history if omitted)",
        ],
        "flags": [
            ("--id TABLE",      "Table full name (catalog.schema.table)"),
            ("--name TABLE",    "Alias for --id"),
            ("--warehouse ID",  "Warehouse ID — auto-detected from query history if omitted"),
            ("--rows N",        "Fetch N sample rows — omit to skip data query entirely"),
        ],
        "required_flags": ["--id"],
        "fn": run_table_meta,
    },
    "schema-meta": {
        "description": "All tables in a schema with column counts and optional row counts",
        "activity": ["info", "data"], "type": "R",
        "noise": "Low without --warehouse; Medium+ with (one COUNT(*) per table)",
        "prereqs": ["Catalog name", "Schema name"],
        "caveats": ["Row counts require --warehouse — one SQL call per table"],
        "flags": [
            ("--catalog NAME",  "Catalog name"),
            ("--schema NAME",   "Schema name"),
            ("--warehouse ID",  "Warehouse ID for row counts (optional)"),
        ],
        "required_flags": ["--catalog", "--schema"],
        "fn": run_schema_meta,
    },
    "temp-path-creds": {
        "description": "Generate temporary STS/SAS creds for an external location URL",
        "activity": ["cred", "latm"], "type": "R", "noise": "Low — API only, no cluster",
        "prereqs": ["External location URL — from uc external-locations"],
        "caveats": ["Returns actual cloud credentials without IMDS or cluster access"],
        "flags": [("--path URL", "External location URL (s3:// or abfss://)"), ("--id URL", "Alias for --path")],
        "required_flags": ["--path"],
        "fn": run_temp_path_creds,
    },
    "temp-table-creds": {
        "description": "Generate direct storage creds for a table's underlying Parquet files",
        "activity": ["cred", "data"], "type": "R", "noise": "Low — bypasses Databricks audit log",
        "prereqs": ["SELECT on target table", "Table full name (catalog.schema.table)"],
        "caveats": [
            "Direct S3/ADLS access — not visible in Databricks SQL audit logs",
            "Requires SELECT privilege on the table",
        ],
        "flags": [("--id TABLE", "Table full name (catalog.schema.table)"), ("--name TABLE", "Alias for --id")],
        "required_flags": ["--id"],
        "fn": run_temp_table_creds,
    },
}
