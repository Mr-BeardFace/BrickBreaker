"""Profile management — INI file at ~/.brickbreaker/profiles"""

import configparser
import sys
from pathlib import Path

CONFIG_DIR    = Path.home() / ".brickbreaker"
PROFILES_FILE = CONFIG_DIR / "profiles"
STATE_FILE    = CONFIG_DIR / "state"


def ensure_config_dir():
    CONFIG_DIR.mkdir(exist_ok=True)
    if not PROFILES_FILE.exists():
        PROFILES_FILE.write_text("[default]\nhost = \ntoken = \n")
    if not STATE_FILE.exists():
        STATE_FILE.write_text("default")


def load_profiles() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(PROFILES_FILE)
    return cfg


def get_active_profile() -> str:
    ensure_config_dir()
    try:
        return STATE_FILE.read_text().strip() or "default"
    except Exception:
        return "default"


def get_profile_config(name: str) -> dict:
    cfg = load_profiles()
    if name not in cfg:
        from bb.core.display import console
        console.print(f"[red]Profile '{name}' not found. Run: brickbreaker.py profile list[/red]")
        sys.exit(1)
    return dict(cfg[name])


def cmd_profile(args: list):
    from bb.core.display import console
    from rich import box
    from rich.table import Table

    ensure_config_dir()

    if not args:
        active = get_active_profile()
        cfg    = load_profiles()
        host   = cfg.get(active, "host", fallback="(not set)")
        console.print(f"Active profile: [cyan]{active}[/cyan]  {host}")
        return

    sub = args[0]

    if sub == "list":
        active = get_active_profile()
        cfg    = load_profiles()
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Profile", style="cyan")
        t.add_column("Host")
        t.add_column("")
        for section in cfg.sections():
            host = cfg.get(section, "host", fallback="(not set)")
            mark = "[green]* active[/green]" if section == active else ""
            t.add_row(section, host, mark)
        console.print(t)

    elif sub == "--set" and len(args) > 1:
        name = args[1]
        cfg  = load_profiles()
        if name not in cfg:
            console.print(f"[red]Profile '{name}' not found.[/red]")
            sys.exit(1)
        STATE_FILE.write_text(name)
        console.print(f"[green]Active profile → {name}[/green]")

    elif sub == "add":
        name  = input("Profile name    : ").strip()
        host  = input("Host (https://...): ").strip()
        token = input("Token (dapi...)  : ").strip()
        cfg   = load_profiles()
        cfg[name] = {"host": host, "token": token}
        with open(PROFILES_FILE, "w") as f:
            cfg.write(f)
        console.print(f"[green]Profile '{name}' saved.[/green]")

    else:
        console.print("Usage:  profile list | profile --set <name> | profile add")
