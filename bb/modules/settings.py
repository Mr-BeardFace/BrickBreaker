"""Settings module — workspace config, compliance profile, notification destinations"""

from bb.core.display import console
from rich import box
from rich.table import Table


def run_dump(w, conn, profile, flags):
    console.print("\n[bold]Workspace Settings[/bold]  [dim](admin only)[/dim]\n")

    # Workspace config
    try:
        cfg = w.workspace_conf.get_status(keys=",".join([
            "enableTokensConfig", "maxTokenLifetimeDays",
            "enableIpAccessLists", "enableResultsDownloading",
            "enableNotebookTableClipboard", "enableExportNotebook",
        ]))
        console.print("[bold]Workspace Config[/bold]")
        t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        t.add_column("Key",   style="dim", min_width=36)
        t.add_column("Value", style="cyan")
        for k, v in (cfg or {}).items():
            t.add_row(k, str(v))
        console.print(t)
    except Exception as e:
        console.print(f"  [red]workspace_conf error: {e}[/red]")

    # Compliance / security profile
    try:
        console.print("\n[bold]Compliance Security Profile[/bold]")
        csp = w.settings.compliance_security_profile.get()
        ws  = csp.compliance_security_profile_workspace
        console.print(f"  Enabled       : {ws.is_enabled if ws else '?'}")
        features = (ws.compliance_standards or []) if ws else []
        for f in features:
            console.print(f"  Standard      : {f.value if hasattr(f,'value') else f}")
    except Exception as e:
        console.print(f"  [dim]compliance_security_profile: {e}[/dim]")

    # Notification destinations
    try:
        console.print("\n[bold]Notification Destinations[/bold]")
        dests = list(w.notification_destinations.list())
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",   style="dim")
        t.add_column("Name", style="cyan")
        t.add_column("Type")
        for d in dests:
            t.add_row(str(d.id), d.display_name or "?",
                      d.destination_type.value if d.destination_type else "?")
        console.print(t)
    except Exception as e:
        console.print(f"  [red]notification_destinations error: {e}[/red]")


COMMANDS = {
    "dump": {
        "description": "Dump workspace config, compliance profile, notification destinations",
        "activity": ["info"], "type": "R", "noise": "Low — single-shot, 3 API calls",
        "prereqs": ["Admin token recommended (some fields restricted)"],
        "caveats": ["Partial results returned if non-admin — no error thrown"],
        "flags": [],
        "fn": run_dump,
    },
}
