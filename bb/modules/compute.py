"""Compute module — clusters, init scripts, instance profiles, command execution"""

import base64
import time

from bb.core.db import now_iso, log_pull, fmt_epoch_ms, should_use_cache
from bb.core.display import console, write_output, next_step
from rich import box
from rich.table import Table


def run_clusters(w, conn, profile, flags):
    module = "compute.clusters"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM clusters ORDER BY cluster_name").fetchall()
        console.print(f"\n[bold]Running Clusters[/bold]  [dim](cached {age})[/dim]\n")
        for r in rows:
            console.print(f"  [cyan]{r['cluster_id']}[/cyan]  {r['cluster_name'] or '(no name)'}")
            console.print(f"    owner   : {r['owner'] or '?'}")
            console.print(f"    profile : {r['instance_profile'] or '[dim]none[/dim]'}")
            console.print()
        return

    console.print("\n[bold]Running Clusters[/bold]\n")
    try:
        from databricks.sdk.service.compute import ListClustersFilterBy, State as CState
        clusters = list(w.clusters.list(
            filter_by=ListClustersFilterBy(cluster_states=[CState.RUNNING])
        ))
        now_ts  = time.time()
        now     = now_iso()
        conn.execute("DELETE FROM clusters")

        if not clusters:
            console.print("[yellow]No running clusters found[/yellow]")
            return

        for c in clusters:
            iprofile = (c.aws_attributes.instance_profile_arn if c.aws_attributes else None) or ""
            conn.execute(
                "INSERT OR REPLACE INTO clusters VALUES (?,?,?,?,?,?,?)",
                (c.cluster_id, c.cluster_name, c.creator_user_name, iprofile,
                 c.autotermination_minutes, c.last_restarted_time, now)
            )
            auto_min  = c.autotermination_minutes or 0
            last_act  = c.last_restarted_time or 0
            if auto_min == 0:
                window = "[green]always-on[/green]"
            else:
                remaining = ((last_act / 1000) + (auto_min * 60)) - now_ts
                if remaining > 0:
                    mins  = int(remaining / 60)
                    color = "green" if mins > 30 else ("yellow" if mins > 10 else "red")
                    window = f"[{color}]~{mins}m remaining[/{color}]"
                else:
                    window = "[red]terminating soon[/red]"

            console.print(f"  [cyan]{c.cluster_id}[/cyan]  {c.cluster_name or '(no name)'}")
            console.print(f"    owner    : {c.creator_user_name or '?'}")
            console.print(f"    profile  : {iprofile or '[dim]none[/dim]'}")
            console.print(f"    window   : {window}")
            console.print()

        log_pull(conn, module, profile, len(clusters))
        conn.commit()
        next_step("compute cluster-get --id <cluster_id> --run",
                  "secrets dump --cluster <cluster_id> --aggressive --run",
                  "imds aws --cluster <cluster_id> --aggressive --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_cluster_get(w, conn, profile, flags):
    cluster_id = flags.get("id")
    if not cluster_id:
        cluster_id = input("Cluster ID (from: compute clusters --run)  e.g. 0123-456789-abc1def2: ").strip()
    console.print(f"\n[bold]Cluster Config[/bold]  [dim]{cluster_id}[/dim]\n")
    try:
        c        = w.clusters.get(cluster_id=cluster_id)
        env_vars = c.spark_env_vars or {}
        if env_vars:
            console.print("[bold]Spark Env Vars[/bold]")
            for k, v in env_vars.items():
                console.print(f"  [cyan]{k}[/cyan] = {v}")
        else:
            console.print("[dim]spark_env_vars: (none)[/dim]")

        if c.aws_attributes and c.aws_attributes.instance_profile_arn:
            console.print("\n[bold]Instance Profile[/bold]")
            console.print(f"  [yellow]{c.aws_attributes.instance_profile_arn}[/yellow]")

        scripts = c.init_scripts or []
        if scripts:
            console.print("\n[bold]Init Scripts[/bold]")
            for s in scripts:
                path = (s.dbfs.destination     if s.dbfs      else None) or \
                       (s.workspace.destination if s.workspace else None) or \
                       (s.s3.destination        if s.s3        else "?")
                console.print(f"  {path}")

        if c.ssh_public_keys:
            console.print("\n[bold]SSH Public Keys[/bold]")
            for k in c.ssh_public_keys:
                console.print(f"  {k[:72]}…")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_init_scripts_list(w, conn, profile, flags):
    module = "compute.init-scripts-list"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM init_scripts ORDER BY position").fetchall()
        console.print(f"\n[bold]Global Init Scripts[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",       style="dim")
        t.add_column("Name",     style="cyan")
        t.add_column("Position", justify="right")
        t.add_column("Enabled")
        for r in rows:
            t.add_row(r["script_id"], r["name"],
                      str(r["position"]),
                      "[green]Yes[/green]" if r["enabled"] else "[red]No[/red]")
        console.print(t)
        return

    console.print("\n[bold]Global Init Scripts[/bold]\n")
    try:
        scripts = list(w.global_init_scripts.list())
        now     = now_iso()
        t       = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",       style="dim")
        t.add_column("Name",     style="cyan")
        t.add_column("Position", justify="right")
        t.add_column("Enabled")
        for s in scripts:
            t.add_row(s.script_id, s.name, str(s.position),
                      "[green]Yes[/green]" if s.enabled else "[red]No[/red]")
            conn.execute(
                "INSERT OR REPLACE INTO init_scripts VALUES (?,?,?,?,?,?)",
                (s.script_id, s.name, s.position, int(bool(s.enabled)), None, now)
            )
        log_pull(conn, module, profile, len(scripts))
        conn.commit()
        console.print(t)
        next_step("compute init-script-get --id <script_id> --run",
                  "compute init-script-get --id <script_id> --output <file> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_init_script_get(w, conn, profile, flags):
    script_id = flags.get("id")
    if not script_id:
        script_id = input("Script ID (from: compute init-scripts-list --run)  e.g. ABCDEF1234567890: ").strip()
    console.print(f"\n[bold]Init Script Content[/bold]  [dim]{script_id}[/dim]\n")
    try:
        s       = w.global_init_scripts.get(script_id=script_id)
        content = base64.b64decode(s.script or "").decode("utf-8", errors="replace")
        write_output(content, flags)
        conn.execute("UPDATE init_scripts SET content=? WHERE script_id=?", (content, script_id))
        conn.commit()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_instance_profiles(w, conn, profile, flags):
    module = "compute.instance-profiles"
    console.print("\n[bold]Instance Profiles (AWS)[/bold]\n")
    try:
        profiles = list(w.instance_profiles.list())
        t        = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("IAM Role ARN",  style="yellow")
        t.add_column("Meta Master")
        for p in profiles:
            t.add_row(p.instance_profile_arn or "?",
                      "Yes" if p.is_meta_instance_profile else "")
        log_pull(conn, module, profile, len(profiles))
        conn.commit()
        console.print(t)
        next_step("compute clusters --run",
                  "imds aws --cluster <cluster_id> --aggressive --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_execute(w, conn, profile, flags):
    """Execute a command on a running cluster (EXEC — requires --aggressive)"""
    if not flags.get("aggressive"):
        console.print("[yellow]EXEC operation — requires --aggressive flag[/yellow]")
        return

    cluster_id = flags.get("cluster") or flags.get("id")
    if not cluster_id:
        cluster_id = input("Cluster ID (from: compute clusters --run)  e.g. 0123-456789-abc1def2: ").strip()
    cmd = flags.get("sql") or input("Command (Python): ").strip()

    console.print(f"\n[bold]Executing on[/bold] [cyan]{cluster_id}[/cyan]\n")
    try:
        from databricks.sdk.service.compute import Language
        ctx = w.command_execution.create(cluster_id=cluster_id, language=Language.PYTHON).result()
        result = w.command_execution.execute(
            cluster_id=cluster_id,
            context_id=ctx.id,
            language=Language.PYTHON,
            command=cmd,
        ).result()
        if result.results:
            write_output(result.results.data or "(no output)", flags)
        w.command_execution.destroy(cluster_id=cluster_id, context_id=ctx.id)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_delete_cluster(w, conn, profile, flags):
    cluster_id = flags.get("cluster") or flags.get("id")
    if not cluster_id:
        cluster_id = input("Cluster ID (from: compute clusters --run)  e.g. 0123-456789-abc1def2: ").strip()

    console.print(f"\n[bold]Delete Cluster[/bold]  [dim]{cluster_id}[/dim]\n")
    console.print("  [yellow]W operation — permanently deletes the cluster[/yellow]\n")
    confirm = input("  Confirm delete? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("[dim]Cancelled[/dim]")
        return

    try:
        w.clusters.permanent_delete(cluster_id=cluster_id)
        console.print(f"  [green]Deleted[/green]  {cluster_id}")
        conn.execute("DELETE FROM clusters WHERE cluster_id=?", (cluster_id,))
        conn.commit()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_create_cluster(w, conn, profile, flags):
    cluster_name = flags.get("name") or f"bb-temp-{now_iso()[:10]}"
    node_type    = flags.get("id") or flags.get("cluster")

    console.print("\n[bold]Create Temporary Cluster[/bold]\n")
    console.print("  [yellow]W operation — creates a cluster visible in workspace[/yellow]\n")

    # Auto-detect latest LTS spark version
    try:
        versions = w.clusters.spark_versions()
        lts = [v for v in (versions.versions or [])
               if v.key and "lts" in v.key.lower() and "ml" not in v.key.lower()]
        spark_ver = lts[0].key if lts else "14.3.x-scala2.12"
    except Exception:
        spark_ver = "14.3.x-scala2.12"

    if not node_type:
        console.print(f"  Spark version : {spark_ver}")
        console.print(f"  Cluster name  : {cluster_name}")
        console.print(f"  Auto-terminate: 30 min")
        console.print(f"  Workers       : 0 (single-node)\n")
        node_type = input("  Node type ID  e.g. m5.large (AWS) / Standard_D3_v2 (Azure) / n1-standard-4 (GCP): ").strip()
        if not node_type:
            console.print("[red]Node type required[/red]")
            return

    console.print(f"\n  name={cluster_name}  node={node_type}  spark={spark_ver}  autoterminate=30min\n")
    confirm = input("  Confirm create cluster? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("[dim]Cancelled[/dim]")
        return

    console.print("  [dim]Creating cluster — waiting for RUNNING state...[/dim]")
    try:
        cluster = w.clusters.create(
            cluster_name=cluster_name,
            spark_version=spark_ver,
            node_type_id=node_type,
            num_workers=0,
            spark_conf={"spark.databricks.cluster.profile": "singleNode",
                        "spark.master": "local[*]"},
            custom_tags={"ResourceClass": "SingleNode"},
            autotermination_minutes=30,
        ).result()

        cid = cluster.cluster_id
        console.print(f"\n  [green]RUNNING[/green]  cluster_id=[cyan]{cid}[/cyan]")
        console.print(f"  [dim]Auto-terminates in 30 min of inactivity[/dim]")
        next_step(
            f"secrets dump --cluster {cid} --aggressive --run",
            f"imds aws --cluster {cid} --aggressive --run",
            f"compute execute --cluster {cid} --aggressive --run",
            f"compute delete-cluster --cluster {cid} --run",
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "clusters": {
        "description": "List running clusters — owner, instance profile, time window",
        "activity": ["info"], "type": "R", "noise": "Low — server-side RUNNING filter",
        "prereqs": [],
        "caveats": ["Non-admin sees own clusters only"],
        "flags": [],
        "fn": run_clusters,
    },
    "cluster-get": {
        "description": "Full config for a cluster: env vars, instance profile, init scripts",
        "activity": ["cred", "latm"], "type": "R", "noise": "Low",
        "prereqs": ["Cluster ID — from compute clusters"],
        "caveats": ["Requires CAN_MANAGE on cluster or admin"],
        "flags": [("--id ID", "Cluster ID")],
        "required_flags": ["--id"],
        "fn": run_cluster_get,
    },
    "init-scripts-list": {
        "description": "List global init scripts (IDs and names — no content)",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": ["Admin token required"],
        "caveats": ["Content not returned in list — use init-script-get per ID"],
        "flags": [],
        "fn": run_init_scripts_list,
    },
    "init-script-get": {
        "description": "Retrieve full content of a global init script (base64 decoded)",
        "activity": ["cred"], "type": "R", "noise": "Low",
        "prereqs": ["Admin token required", "Script ID — from init-scripts-list"],
        "caveats": ["High-value — scripts run on every cluster, often contain hardcoded creds"],
        "flags": [("--id ID", "Script ID"), ("--output FILE", "Save content to file")],
        "required_flags": ["--id"],
        "fn": run_init_script_get,
    },
    "instance-profiles": {
        "description": "List IAM role ARNs registered for cluster attachment (AWS)",
        "activity": ["latm"], "type": "R", "noise": "Low",
        "prereqs": ["Admin token required", "AWS workspace only"],
        "caveats": [],
        "flags": [],
        "fn": run_instance_profiles,
    },
    "execute": {
        "description": "Run arbitrary code on a running cluster",
        "activity": ["data", "cred"], "type": "EXEC", "noise": "High — creates execution context",
        "prereqs": ["Running cluster ID", "--aggressive flag"],
        "caveats": [
            "Secret values may be [REDACTED] in output — use base64 encoding as workaround",
            "Cluster start is separate and explicit — this assumes cluster is already running",
        ],
        "flags": [
            ("--cluster ID",  "Cluster ID"),
            ("--id ID",       "Alias for --cluster"),
            ("--sql TEXT",    "Command to run (prompts if omitted)"),
            ("--output FILE", "Save output to file"),
        ],
        "required_flags": ["--cluster"],
        "aggressive": ["Cluster code execution"],
        "fn": run_execute,
    },
    "delete-cluster": {
        "description": "Terminate and permanently delete a cluster",
        "activity": ["info"], "type": "W", "noise": "Low — single API call",
        "prereqs": ["Cluster ID — from compute clusters or compute create-cluster"],
        "caveats": ["Permanent — cluster config is deleted, not just stopped"],
        "flags": [
            ("--cluster ID", "Cluster ID"),
            ("--id ID",      "Alias for --cluster"),
        ],
        "required_flags": ["--cluster"],
        "fn": run_delete_cluster,
    },
    "create-cluster": {
        "description": "Create a minimal single-node cluster and wait for RUNNING state",
        "activity": ["latm"], "type": "W", "noise": "High — cluster visible in workspace UI and audit log",
        "prereqs": ["Node type ID for the workspace's cloud (m5.large / Standard_D3_v2 / n1-standard-4)"],
        "caveats": [
            "Cluster creation is logged and visible to workspace admins immediately",
            "Auto-terminates after 30 min of inactivity",
            "Spark version auto-detected as latest LTS",
        ],
        "flags": [
            ("--name NAME",   "Cluster name (default: bb-temp-<date>)"),
            ("--id TYPE",     "Node type ID — prompts if omitted"),
        ],
        "fn": run_create_cluster,
    },
}
