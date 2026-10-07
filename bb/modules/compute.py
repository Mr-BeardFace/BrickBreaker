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
        cluster_id = input("Cluster ID (from: compute clusters --run): ").strip()
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
        script_id = input("Script ID (from: compute init-scripts-list --run): ").strip()
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
        cluster_id = input("Cluster ID (from: compute clusters --run): ").strip()
    cmd = flags.get("sql") or input("Command: ").strip()

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
}
