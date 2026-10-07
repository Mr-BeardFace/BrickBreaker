"""Rich console, colors, and CLI display helpers"""

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import io, sys


class _TeeConsole:
    """Wraps a Rich Console and optionally tees output to a plain-text file."""

    def __init__(self, term_console: Console):
        self._term = term_console
        self._file = None
        self._file_con = None

    def begin_output(self, path: str):
        self._file = open(path, "w", encoding="utf-8")
        self._file_con = Console(file=self._file, no_color=True, highlight=False,
                                 width=200)

    def end_output(self):
        if self._file_con:
            self._file_con = None
        if self._file:
            self._file.close()
            self._file = None

    def print(self, *args, **kwargs):
        self._term.print(*args, **kwargs)
        if self._file_con:
            self._file_con.print(*args, **kwargs)

    def rule(self, *args, **kwargs):
        self._term.rule(*args, **kwargs)
        if self._file_con:
            self._file_con.rule(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._term, name)


_term = Console(file=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
                if hasattr(sys.stdout, "buffer") else sys.stdout)
console = _TeeConsole(_term)

VERSION   = "0.1.0"
TOOL_NAME = "BrickBreaker"

TYPE_COLORS  = {"R": "green", "R*": "yellow", "W": "red", "EXEC": "magenta"}
NOISE_COLORS = {"Low": "green", "Medium": "yellow", "High": "red"}
ACT_COLORS   = {"info": "blue", "cred": "red", "latm": "magenta", "data": "cyan", "persist": "green"}
ACT_LABELS   = {"info": "Info", "cred": "Cred Pull", "latm": "Lat Move", "data": "Data", "persist": "Persist"}


def next_step(*commands: str):
    """Print one or more follow-up command suggestions after a result."""
    console.print()
    for cmd in commands:
        console.print(f"  [dim]↳[/dim] [cyan]{cmd}[/cyan]")


def write_output(content: str, flags: dict, label: str = "output"):
    """Write content to --output file if specified, otherwise print to console."""
    path = flags.get("output")
    if path:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            console.print(f"  [green]Saved to {path}[/green]")
        except Exception as e:
            console.print(f"  [red]Failed to write {path}: {e}[/red]")
            console.print(content)
    else:
        console.print(content)


def print_header(profile: str):
    from bb.core.config import get_profile_config
    cfg  = get_profile_config(profile)
    host = cfg.get("host", "(no host)")
    console.rule(
        f"[bold cyan]{TOOL_NAME}[/bold cyan]  [dim]│[/dim]  "
        f"profile: [cyan]{profile}[/cyan]  [dim]│[/dim]  [dim]{host}[/dim]",
        style="dim"
    )


def acts(activity: list) -> str:
    return "  ".join(
        f"[{ACT_COLORS.get(a, 'white')}]{ACT_LABELS.get(a, a)}[/{ACT_COLORS.get(a, 'white')}]"
        for a in activity
    )


def show_module_info(category: str, command: str):
    from bb.registry import MODULES
    m = MODULES.get(category, {}).get("commands", {}).get(command)
    if not m:
        console.print(f"[red]Unknown: {category} {command}[/red]")
        return

    t     = m["type"]
    color = TYPE_COLORS.get(t, "white")
    noise = m.get("noise", "?")
    nc    = NOISE_COLORS.get(noise.split()[0], "white")

    lines = [
        f"[bold]{m['description']}[/bold]\n",
        f"  Type      [{color}]{t}[/{color}]",
        f"  Activity  {acts(m.get('activity', []))}",
        f"  Noise     [{nc}]{noise}[/{nc}]",
        f"  Prereqs   {', '.join(m['prereqs']) if m.get('prereqs') else 'None'}",
    ]

    if m.get("caveats"):
        lines += ["", "  [yellow]Caveats[/yellow]"]
        lines += [f"    [yellow]⚠[/yellow] {c}" for c in m["caveats"]]

    if m.get("flags"):
        required = set(m.get("required_flags", []))
        lines += ["", "  [cyan]Flags[/cyan]"]
        for flag, help_text in m["flags"]:
            flag_key = flag.split()[0]  # e.g. "--scope" from "--scope NAME"
            req_mark = " [red]*[/red]" if flag_key in required else ""
            lines.append(f"    [cyan]{flag:<26}[/cyan]{req_mark} {help_text}")
        if required:
            lines.append("    [dim red]* required[/dim red]")

    if m.get("aggressive"):
        lines += ["", "  [magenta]--aggressive unlocks[/magenta]"]
        lines += [f"    [magenta]→[/magenta] {a}" for a in m["aggressive"]]

    lines += ["", "  [dim]Add --run to execute  ·  --cached  ·  --fresh  ·  --extended  ·  --output <file>[/dim]"]

    console.print(Panel(
        "\n".join(lines),
        title=f"[bold]{category}[/bold] › [bold cyan]{command}[/bold cyan]",
        border_style="dim",
        padding=(0, 1),
    ))


def show_category(category: str):
    from bb.registry import MODULES
    if category not in MODULES:
        console.print(f"[red]Unknown category: {category}[/red]  "
                      f"Available: {', '.join(MODULES)}")
        return

    cat = MODULES[category]
    t   = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
    t.add_column("Command",  style="cyan", min_width=24)
    t.add_column("Type",     min_width=5)
    t.add_column("Activity", min_width=28)
    t.add_column("Description")

    for name, m in cat["commands"].items():
        tc = TYPE_COLORS.get(m["type"], "white")
        t.add_row(
            name,
            f"[{tc}]{m['type']}[/{tc}]",
            acts(m.get("activity", [])),
            m["description"],
        )

    console.print(f"\n[bold]{category}[/bold] — {cat['description']}\n")
    console.print(t)
    console.print(
        f"\n  [dim]brickbreaker.py {category} <command> [flags] --run[/dim]\n"
        f"  [dim]brickbreaker.py {category} <command>           — show info pane[/dim]\n"
    )


def show_top_menu():
    from bb.registry import MODULES

    cat_table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    cat_table.add_column("Cat",  style="cyan", min_width=12)
    cat_table.add_column("Desc", style="dim")
    for name, cat in MODULES.items():
        cat_table.add_row(name, cat["description"])

    act_table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    act_table.add_column("Activity", min_width=10)
    act_table.add_column("Desc",     style="dim")
    act_table.add_row("[blue]info[/blue]",      "Information gathering")
    act_table.add_row("[red]cred[/red]",        "Credential extraction")
    act_table.add_row("[magenta]latm[/magenta]", "Lateral movement")
    act_table.add_row("[cyan]data[/cyan]",      "Data access")
    act_table.add_row("[green]persist[/green]", "Persistence")

    console.print(f"\n[bold]{TOOL_NAME}[/bold] [dim]v{VERSION}[/dim]\n")
    console.print(Columns([
        Panel(cat_table, title="[bold]By Category[/bold]", border_style="dim"),
        Panel(act_table, title="[bold]By Activity[/bold]", border_style="dim"),
    ]))
    console.print(
        f"\n  [dim]brickbreaker.py <category>                   — list commands[/dim]\n"
        f"  [dim]brickbreaker.py <category> <command>          — show info pane[/dim]\n"
        f"  [dim]brickbreaker.py <category> <command> --run    — execute[/dim]\n"
        f"  [dim]brickbreaker.py profile --set <name>          — switch profile[/dim]\n"
    )
