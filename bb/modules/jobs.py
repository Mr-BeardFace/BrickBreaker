"""Jobs module — job configs, spark env vars, git source"""

import json

from bb.core.db import now_iso, log_pull, fmt_epoch_ms, should_use_cache
from bb.core.display import console, next_step
from bb.core.flags import limit
from rich import box
from rich.table import Table


def run_list(w, conn, profile, flags):
    module = "jobs.list"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM jobs ORDER BY name").fetchall()
        console.print(f"\n[bold]Jobs[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Job ID",   style="dim")
        t.add_column("Name",     style="cyan")
        t.add_column("Creator")
        t.add_column("Schedule")
        for r in rows:
            t.add_row(r["job_id"], r["name"] or "?", r["creator"] or "?", r["schedule"] or "")
        console.print(t)
        next_step("jobs get --id <job_id> --run")
        return

    console.print("\n[bold]Jobs[/bold]\n")
    try:
        jobs  = list(w.jobs.list())
        shown = limit(jobs, flags["limit"])
        now   = now_iso()

        conn.execute("DELETE FROM jobs")
        for j in jobs:
            sched = None
            if j.settings and j.settings.schedule:
                sched = j.settings.schedule.quartz_cron_expression
            conn.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?)",
                (str(j.job_id), j.settings.name if j.settings else "?",
                 j.creator_user_name, sched, now)
            )
        log_pull(conn, module, profile, len(jobs))
        conn.commit()

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Job ID",   style="dim")
        t.add_column("Name",     style="cyan")
        t.add_column("Creator")
        t.add_column("Schedule")
        for j in shown:
            name  = j.settings.name if j.settings else "?"
            sched = ""
            if j.settings and j.settings.schedule:
                sched = j.settings.schedule.quartz_cron_expression or ""
            t.add_row(str(j.job_id), name, j.creator_user_name or "?", sched)
        console.print(t)
        if flags["limit"] > 0 and len(jobs) > flags["limit"]:
            console.print(f"[dim]  {len(jobs)} total — showing {flags['limit']}[/dim]")
        next_step("jobs get --id <job_id> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_get(w, conn, profile, flags):
    job_id = flags.get("id")
    if not job_id:
        job_id = input("Job ID (from: jobs list --run)  e.g. 123456789: ").strip()
    console.print(f"\n[bold]Job Config[/bold]  [dim]{job_id}[/dim]\n")
    try:
        j    = w.jobs.get(job_id=int(job_id))
        s    = j.settings
        now  = now_iso()

        # Spark env vars (high value) — check cluster-level, job-level, and task notebook params
        env_vars = {}
        if s and getattr(s, "new_cluster", None) and s.new_cluster.spark_env_vars:
            env_vars = s.new_cluster.spark_env_vars
        elif s and getattr(s, "spark_env_vars", None):
            env_vars = s.spark_env_vars

        # Serverless jobs store creds as notebook task base_parameters
        task_params = {}
        tasks = (getattr(s, "tasks", None) if s else None) or []
        for task in tasks:
            if task.notebook_task and task.notebook_task.base_parameters:
                task_params.update(task.notebook_task.base_parameters)

        if env_vars:
            console.print("[bold]Spark Env Vars[/bold]")
            for k, v in env_vars.items():
                console.print(f"  [cyan]{k}[/cyan] = {v}")
        elif task_params:
            console.print("[bold]Task Parameters (notebook base_parameters)[/bold]")
            for k, v in task_params.items():
                console.print(f"  [cyan]{k}[/cyan] = {v}")
        else:
            console.print("[dim]spark_env_vars / task_params: (none)[/dim]")

        # Git source
        if s and getattr(s, "git_source", None):
            gs = s.git_source
            console.print("\n[bold]Git Source[/bold]")
            console.print(f"  url      : [cyan]{gs.git_url}[/cyan]")
            console.print(f"  provider : {gs.git_provider.value if gs.git_provider else '?'}")
            console.print(f"  branch   : {gs.git_branch or '?'}")

        # Libraries
        libs = (getattr(s, "libraries", None) if s else None) or []
        if libs:
            console.print("\n[bold]Libraries[/bold]")
            for lib in libs:
                if lib.pypi:
                    console.print(f"  pypi: {lib.pypi.package}")
                elif lib.maven:
                    console.print(f"  maven: {lib.maven.coordinates}")
                elif lib.whl:
                    console.print(f"  whl: {lib.whl}")
                elif lib.jar:
                    console.print(f"  jar: {lib.jar}")

        if tasks:
            console.print(f"\n[bold]Tasks[/bold]  [dim]({len(tasks)} total)[/dim]")
            for task in tasks[:10]:
                console.print(f"  {task.task_key or '?'}")

        conn.execute(
            "INSERT OR REPLACE INTO job_configs VALUES (?,?,?,?,?)",
            (str(j.job_id), json.dumps({}),
             json.dumps(env_vars or task_params),
             str(s.git_source.git_url if s and getattr(s, "git_source", None) else ""), now)
        )
        conn.commit()
        next_step(f"jobs run --id {job_id} --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_run(w, conn, profile, flags):
    job_id = flags.get("id")
    if not job_id:
        job_id = input("Job ID (from: jobs list --run)  e.g. 123456789: ").strip()

    console.print(f"\n[bold]Trigger Job Run[/bold]  [dim]job_id={job_id}[/dim]\n")
    console.print("  [yellow]W operation — this will create a job run[/yellow]\n")
    confirm = input("  Confirm trigger run? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("[dim]Cancelled[/dim]")
        return

    try:
        waiter = w.jobs.run_now(job_id=int(job_id))
        run_id = waiter._bind.get("run_id", "?")
        console.print(f"\n  Run triggered  [cyan]run_id={run_id}[/cyan]")
        console.print(f"  [dim]Runs as the job's configured identity / cluster[/dim]")
        console.print(f"  [dim]Run history visible in Jobs UI under job {job_id}[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "list": {
        "description": "List all jobs — IDs, names, creator, schedule",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [],
        "flags": [("--limit N", "Max results — default 100, 0=all")],
        "fn": run_list,
    },
    "get": {
        "description": "Full job config — spark env vars, git source, libraries",
        "activity": ["cred", "info"], "type": "R", "noise": "Low",
        "prereqs": ["Job ID — from jobs list"],
        "caveats": ["Spark env vars are a common credential source"],
        "flags": [("--id ID", "Job ID")],
        "required_flags": ["--id"],
        "fn": run_get,
    },
    "run": {
        "description": "Trigger an existing job run — executes as the job's configured identity",
        "activity": ["latm", "persist"], "type": "W", "noise": "Low — single API call, appears in job run history",
        "prereqs": ["Job ID — from jobs list"],
        "caveats": [
            "Run appears in Jobs UI history under the job — visible to workspace admins",
            "Runs as the job's service principal or identity, which may have higher privilege",
            "Does not wait for completion — returns run_id immediately",
        ],
        "flags": [("--id ID", "Job ID")],
        "required_flags": ["--id"],
        "fn": run_run,
    },
}
