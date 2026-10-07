"""Persist module — create PATs, OBO tokens, service principals"""

from bb.core.display import console
from rich import box
from rich.table import Table


def run_create_token(w, conn, profile, flags):
    comment     = flags.get("name") or input("Token comment (label): ").strip()
    lifetime_s  = flags.get("limit")
    if lifetime_s == 100:  # default — ask
        raw = input("Lifetime seconds (0=no expiry): ").strip()
        try:
            lifetime_s = int(raw)
        except ValueError:
            lifetime_s = 0

    console.print(f"\n[bold]Create PAT[/bold]  [yellow]W — this writes to the workspace[/yellow]\n")
    console.print(f"  Comment  : {comment}")
    console.print(f"  Lifetime : {'no expiry' if lifetime_s == 0 else f'{lifetime_s}s'}")
    console.print()
    confirm = input("Confirm create token? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("[dim]cancelled[/dim]")
        return

    try:
        kwargs = {"comment": comment}
        if lifetime_s and lifetime_s > 0:
            kwargs["lifetime_seconds"] = lifetime_s
        result = w.tokens.create(**kwargs)
        console.print(f"\n[bold][green]Token created — save this value now, it will NOT be shown again[/green][/bold]\n")
        console.print(f"  [yellow]{result.token_value}[/yellow]")
        console.print(f"\n  Token ID: {result.token_info.token_id if result.token_info else '?'}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_create_obo_token(w, conn, profile, flags):
    """Create OBO (on-behalf-of) token for another user — admin only"""
    app_id       = flags.get("id")
    lifetime_s   = flags.get("limit")

    if not app_id:
        app_id = input("Service principal application ID: ").strip()
    if lifetime_s == 100:
        raw = input("Lifetime seconds: ").strip()
        try:
            lifetime_s = int(raw)
        except ValueError:
            lifetime_s = 3600

    console.print(f"\n[bold]Create OBO Token[/bold]  [yellow]W — admin only[/yellow]\n")
    console.print(f"  App ID   : {app_id}")
    console.print(f"  Lifetime : {lifetime_s}s")
    console.print()
    confirm = input("Confirm? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("[dim]cancelled[/dim]")
        return

    try:
        result = w.token_management.create_obo_token(
            application_id=int(app_id),
            lifetime_seconds=lifetime_s,
        )
        console.print(f"\n[bold][green]OBO Token created — save now[/green][/bold]\n")
        console.print(f"  [yellow]{result.token_value}[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_create_service_principal(w, conn, profile, flags):
    name = flags.get("name") or input("Display name: ").strip()

    console.print(f"\n[bold]Create Service Principal[/bold]  [yellow]W[/yellow]\n")
    console.print(f"  Name : {name}")
    confirm = input("Confirm? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("[dim]cancelled[/dim]")
        return

    try:
        sp = w.service_principals.create(display_name=name)
        console.print(f"\n  [green]Created[/green]  ID={sp.id}  AppID={sp.application_id}")
        console.print(f"  [dim]Create a PAT for this SP: identity tokens --run[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "create-token": {
        "description": "Create a PAT for the current identity",
        "activity": ["persist"], "type": "W", "noise": "Low — one write call",
        "prereqs": [],
        "caveats": [
            "Token value shown ONCE — save immediately",
            "Appears in token_management.list() for admins",
        ],
        "flags": [
            ("--name TEXT",  "Token comment/label"),
            ("--limit N",    "Lifetime in seconds (0=no expiry)"),
        ],
        "fn": run_create_token,
    },
    "create-obo-token": {
        "description": "Create OBO token for a service principal (admin only)",
        "activity": ["persist", "latm"], "type": "W", "noise": "Low",
        "prereqs": ["Admin token", "Service principal application ID"],
        "caveats": [
            "Admin only",
            "Token value shown ONCE — save immediately",
        ],
        "flags": [
            ("--id APP_ID", "Service principal application ID"),
            ("--limit N",   "Lifetime in seconds"),
        ],
        "fn": run_create_obo_token,
    },
    "create-service-principal": {
        "description": "Create a new service principal",
        "activity": ["persist"], "type": "W", "noise": "Low",
        "prereqs": ["Admin token recommended"],
        "caveats": ["Visible in service_principals.list() immediately"],
        "flags": [("--name TEXT", "Display name")],
        "fn": run_create_service_principal,
    },
}
