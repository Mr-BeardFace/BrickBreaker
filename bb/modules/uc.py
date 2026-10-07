"""Unity Catalog module — catalogs, schemas, tables, connections, credentials, grants"""

import json

from bb.core.db import now_iso, log_pull, should_use_cache
from bb.core.display import console
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
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_schemas(w, conn, profile, flags):
    catalog = flags.get("catalog")
    if not catalog:
        catalog = input("Catalog name: ").strip()
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
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_tables(w, conn, profile, flags):
    catalog     = flags.get("catalog")
    schema_name = flags.get("schema")
    if not catalog:
        catalog = input("Catalog name: ").strip()
    if not schema_name:
        schema_name = input("Schema name: ").strip()
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
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_external_locations(w, conn, profile, flags):
    module = "uc.external-locations"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM uc_external_locations ORDER BY name").fetchall()
        console.print(f"\n[bold]External Locations[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",       style="cyan")
        t.add_column("URL",        style="yellow")
        t.add_column("Credential")
        for r in rows:
            t.add_row(r["name"], r["url"] or "?", r["credential"] or "?")
        console.print(t)
        return

    console.print("\n[bold]External Locations[/bold]\n")
    try:
        locs = list(w.external_locations.list())
        now  = now_iso()
        t    = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Name",       style="cyan")
        t.add_column("URL",        style="yellow")
        t.add_column("Credential")
        for loc in locs:
            t.add_row(loc.name or "?", loc.url or "?",
                      loc.credential_name or "?")
            conn.execute(
                "INSERT OR REPLACE INTO uc_external_locations VALUES (?,?,?,?)",
                (loc.name, loc.url, loc.credential_name, now)
            )
        log_pull(conn, module, profile, len(locs))
        conn.commit()
        console.print(t)
        console.print("\n  [dim]Use 'uc temp-path-creds --path <url>' to generate STS/SAS creds[/dim]")
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
        console.print("\n  [dim]Use 'uc connections-get --name <n>' for full options (may include credentials)[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_connections_get(w, conn, profile, flags):
    name = flags.get("name") or flags.get("id")
    if not name:
        name = input("Connection name: ").strip()
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
            from databricks.sdk.service.catalog import SecurableType
            for stype in [SecurableType.CATALOG, SecurableType.SCHEMA, SecurableType.TABLE,
                          SecurableType.EXTERNAL_LOCATION, SecurableType.STORAGE_CREDENTIAL]:
                try:
                    result = w.grants.get(securable_type=stype, full_name=obj)
                    if result.privilege_assignments:
                        console.print(f"\n  [dim]Found as {stype.value}[/dim]")
                        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
                        t.add_column("Principal", style="cyan")
                        t.add_column("Privileges")
                        for pa in result.privilege_assignments:
                            privs = ", ".join(p.value for p in (pa.privileges or []))
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
            from databricks.sdk.service.catalog import SecurableType
            found = 0
            for cat in w.catalogs.list():
                try:
                    g = w.grants.get(securable_type=SecurableType.CATALOG, full_name=cat.name)
                    for pa in (g.privilege_assignments or []):
                        if pa.principal == principal:
                            privs = ", ".join(p.value for p in (pa.privileges or []))
                            console.print(f"  [cyan]catalog:{cat.name}[/cyan]  {privs}")
                            found += 1
                except Exception:
                    pass
            if found == 0:
                console.print("[dim]No catalog-level grants found for that principal[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    else:
        console.print("[red]Provide --id <object_name> or --name <principal>[/red]")


def run_metastore(w, conn, profile, flags):
    console.print("\n[bold]Metastore Info[/bold]\n")
    try:
        m = w.metastores.current()
        t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        t.add_column("Field", style="dim", min_width=24)
        t.add_column("Value")
        t.add_row("Name",           m.name or "?")
        t.add_row("Metastore ID",   m.metastore_id or "?")
        t.add_row("Owner",          m.owner or "?")
        t.add_row("Cloud",          m.cloud or "?")
        t.add_row("Region",         m.region or "?")
        t.add_row("Storage Root",   m.storage_root or "?")
        t.add_row("Default Location", m.storage_root or "?")
        console.print(t)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_volumes(w, conn, profile, flags):
    catalog     = flags.get("catalog")
    schema_name = flags.get("schema")
    if not catalog:
        catalog = input("Catalog name: ").strip()
    if not schema_name:
        schema_name = input("Schema name: ").strip()
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
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_temp_path_creds(w, conn, profile, flags):
    url = flags.get("path") or flags.get("id")
    if not url:
        url = input("External location URL (e.g. s3://bucket/path): ").strip()
    console.print(f"\n[bold]Temporary Path Credentials[/bold]  [dim]{url}[/dim]\n")
    console.print("[yellow]ⓘ R-only API — no cluster required[/yellow]\n")
    try:
        from databricks.sdk.service.catalog import Privilege
        creds = w.temporary_path_credentials.generate(url=url, operation=Privilege.READ_FILES)
        if hasattr(creds, "aws_temp_credentials") and creds.aws_temp_credentials:
            a = creds.aws_temp_credentials
            console.print("[bold]AWS STS Credentials[/bold]")
            console.print(f"  AccessKeyId     : [yellow]{a.access_key_id}[/yellow]")
            console.print(f"  SecretAccessKey : [yellow]{a.secret_access_key}[/yellow]")
            console.print(f"  SessionToken    : [yellow]{a.session_token}[/yellow]")
        elif hasattr(creds, "azure_sas") and creds.azure_sas:
            console.print(f"[bold]Azure SAS Token[/bold]")
            console.print(f"  [yellow]{creds.azure_sas}[/yellow]")
        else:
            console.print(repr(creds))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_temp_table_creds(w, conn, profile, flags):
    table_id = flags.get("id") or flags.get("name")
    if not table_id:
        table_id = input("Table full name (catalog.schema.table): ").strip()
    console.print(f"\n[bold]Temporary Table Credentials[/bold]  [dim]{table_id}[/dim]\n")
    console.print("[yellow]ⓘ Direct storage creds — bypasses Databricks audit logging[/yellow]\n")
    try:
        from databricks.sdk.service.catalog import Privilege
        creds = w.temporary_table_credentials.generate(
            table_id=table_id, operation=Privilege.SELECT
        )
        if hasattr(creds, "aws_temp_credentials") and creds.aws_temp_credentials:
            a = creds.aws_temp_credentials
            console.print("[bold]AWS STS Credentials[/bold]")
            console.print(f"  AccessKeyId     : [yellow]{a.access_key_id}[/yellow]")
            console.print(f"  SecretAccessKey : [yellow]{a.secret_access_key}[/yellow]")
            console.print(f"  SessionToken    : [yellow]{a.session_token}[/yellow]")
        elif hasattr(creds, "azure_sas") and creds.azure_sas:
            console.print(f"[bold]Azure SAS Token[/bold]")
            console.print(f"  [yellow]{creds.azure_sas}[/yellow]")
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
        "flags": [("--name NAME", "Connection name")],
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
            ("--id OBJECT",    "Object full name — returns all grants on it"),
            ("--name PRINCIPAL","Principal name — returns all objects they have access to (R*)"),
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
        "fn": run_volumes,
    },
    "temp-path-creds": {
        "description": "Generate temporary STS/SAS creds for an external location URL",
        "activity": ["cred", "latm"], "type": "R", "noise": "Low — API only, no cluster",
        "prereqs": ["External location URL — from uc external-locations"],
        "caveats": ["Returns actual cloud credentials without IMDS or cluster access"],
        "flags": [("--path URL", "External location URL (s3:// or abfss://)")],
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
        "flags": [("--id TABLE", "Table full name (catalog.schema.table)")],
        "fn": run_temp_table_creds,
    },
}
