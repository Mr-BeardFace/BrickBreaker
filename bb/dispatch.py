"""CLI dispatch — routes category → command → info pane or execution"""

import sys

from bb.core.config import ensure_config_dir, get_active_profile, cmd_profile
from bb.core.client import make_client
from bb.core.db import get_db
from bb.core.display import console, print_header, show_module_info, show_category, show_top_menu
from bb.core.flags import parse_flags, extract_positionals
from bb.registry import MODULES


def dispatch(argv: list):
    ensure_config_dir()

    # Profile management needs no auth
    if argv and argv[0] == "profile":
        cmd_profile(argv[1:])
        return

    flags          = parse_flags(argv)
    active_profile = flags.get("profile") or get_active_profile()
    print_header(active_profile)

    positional = extract_positionals(argv)
    category   = positional[0] if positional else None
    command    = positional[1] if len(positional) > 1 else None

    if not category:
        show_top_menu()
        return

    if category not in MODULES:
        console.print(f"[red]Unknown category: {category}[/red]  "
                      f"Available: {', '.join(MODULES)}")
        return

    if not command:
        show_category(category)
        return

    if not flags["run"]:
        show_module_info(category, command)
        return

    # Execute
    mods = MODULES[category]["commands"]
    if command not in mods:
        console.print(f"[red]Unknown command: {category} {command}[/red]")
        show_category(category)
        return

    fn = mods[command].get("fn")
    if not fn:
        console.print(f"[yellow]'{category} {command}' not yet implemented[/yellow]")
        return

    w        = make_client(active_profile,
                           override_host=flags.get("host"),
                           override_token=flags.get("token"))
    conn     = get_db(active_profile)
    out_path = flags.get("output")
    if out_path:
        console.begin_output(out_path)
    try:
        fn(w, conn, active_profile, flags)
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted[/dim]")
    finally:
        if out_path:
            console.end_output()
            console.print(f"  [green]Saved to {out_path}[/green]")
        conn.close()
