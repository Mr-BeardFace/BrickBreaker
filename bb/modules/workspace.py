"""Workspace module — notebooks, files, git credentials, repos"""

import base64

from bb.core.db import now_iso, log_pull, should_use_cache
from bb.core.display import console
from rich import box
from rich.table import Table


def _walk(w, path: str, depth: int, current: int, conn, now: str):
    try:
        items = list(w.workspace.list(path=path))
    except Exception as e:
        console.print(f"  [red]Error listing {path}: {e}[/red]")
        return 0

    count = 0
    for item in items:
        itype = item.object_type.value if item.object_type else "?"
        lang  = item.language.value if item.language else ""
        indent = "  " * current
        tag   = f"[dim]{lang}[/dim]" if lang else ""
        console.print(f"{indent}[cyan]{item.path}[/cyan]  [dim]{itype}[/dim]  {tag}")
        conn.execute(
            "INSERT OR REPLACE INTO workspace_items VALUES (?,?,?,?,?)",
            (item.path, itype, lang, str(item.object_id or ""), now)
        )
        count += 1
        if itype == "DIRECTORY" and (depth < 0 or current < depth):
            count += _walk(w, item.path, depth, current + 1, conn, now)
    return count


def run_list(w, conn, profile, flags):
    path   = flags.get("path") or "/"
    depth  = flags.get("depth", 0)
    module = f"workspace.list:{path}"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute(
            "SELECT * FROM workspace_items WHERE path LIKE ? ORDER BY path",
            (path.rstrip("/") + "%",)
        ).fetchall()
        console.print(f"\n[bold]Workspace[/bold]  [dim]{path}[/dim]  [dim](cached {age})[/dim]\n")
        for r in rows:
            lang = f"  [dim]{r['language']}[/dim]" if r["language"] else ""
            console.print(f"  [cyan]{r['path']}[/cyan]  [dim]{r['item_type']}[/dim]{lang}")
        return

    console.print(f"\n[bold]Workspace[/bold]  [dim]{path}[/dim]"
                  f"  [dim]depth={'unlimited' if depth < 0 else depth}[/dim]\n")
    now   = now_iso()
    count = _walk(w, path, depth, 0, conn, now)
    log_pull(conn, module, profile, count)
    conn.commit()


def run_export(w, conn, profile, flags):
    path = flags.get("path") or flags.get("id")
    if not path:
        path = input("Workspace path: ").strip()
    console.print(f"\n[bold]Export[/bold]  [dim]{path}[/dim]\n")
    try:
        from databricks.sdk.service.workspace import ExportFormat
        result  = w.workspace.export(path=path, format=ExportFormat.SOURCE)
        content = base64.b64decode(result.content or "").decode("utf-8", errors="replace")
        console.print(content)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_git_credentials(w, conn, profile, flags):
    module = "workspace.git-credentials"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM git_credentials ORDER BY git_username").fetchall()
        console.print(f"\n[bold]Git Credentials[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",       style="dim")
        t.add_column("Username", style="cyan")
        t.add_column("Provider")
        for r in rows:
            t.add_row(r["credential_id"], r["git_username"] or "?", r["git_provider"] or "?")
        console.print(t)
        return

    console.print("\n[bold]Git Credentials[/bold]\n")
    try:
        creds = list(w.git_credentials.list())
        now   = now_iso()
        t     = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",       style="dim")
        t.add_column("Username", style="cyan")
        t.add_column("Provider")
        for c in creds:
            t.add_row(str(c.credential_id), c.git_username or "?",
                      c.git_provider.value if c.git_provider else "?")
            conn.execute(
                "INSERT OR REPLACE INTO git_credentials VALUES (?,?,?,?)",
                (str(c.credential_id), c.git_username,
                 c.git_provider.value if c.git_provider else "?", now)
            )
        log_pull(conn, module, profile, len(creds))
        conn.commit()
        console.print(t)
        console.print("\n  [dim]Tokens stored in git credentials are not returned by the API[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_repos_list(w, conn, profile, flags):
    module = "workspace.repos"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM repos ORDER BY path").fetchall()
        console.print(f"\n[bold]Repos[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",       style="dim")
        t.add_column("Path",     style="cyan")
        t.add_column("Provider")
        t.add_column("Branch")
        t.add_column("URL")
        for r in rows:
            t.add_row(r["id"], r["path"] or "?", r["provider"] or "?",
                      r["branch"] or "?", r["url"] or "?")
        console.print(t)
        return

    console.print("\n[bold]Repos[/bold]\n")
    try:
        repos = list(w.repos.list())
        now   = now_iso()
        t     = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("ID",       style="dim")
        t.add_column("Path",     style="cyan")
        t.add_column("Provider")
        t.add_column("Branch")
        t.add_column("URL")
        for r in repos:
            t.add_row(str(r.id), r.path or "?",
                      r.provider or "?", r.branch or "?", r.url or "?")
            conn.execute(
                "INSERT OR REPLACE INTO repos VALUES (?,?,?,?,?,?)",
                (str(r.id), r.url, r.provider, r.branch, r.path, now)
            )
        log_pull(conn, module, profile, len(repos))
        conn.commit()
        console.print(t)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "list": {
        "description": "List workspace items at a path",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["--depth -1 = unlimited recursion — can be very noisy on large workspaces"],
        "flags": [
            ("--path PATH",  "Workspace path (default: /)"),
            ("--depth N",    "Recursion depth — 0=current dir only, -1=unlimited"),
        ],
        "fn": run_list,
    },
    "export": {
        "description": "Export a notebook or file source (API download)",
        "activity": ["data"], "type": "R", "noise": "Low",
        "prereqs": ["Workspace path"],
        "caveats": ["Downloads file content through API — not a server-side operation"],
        "flags": [("--path PATH", "Workspace path to export")],
        "fn": run_export,
    },
    "git-credentials": {
        "description": "List git credential entries (usernames + providers — no tokens)",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["Token values are never returned by the API"],
        "flags": [],
        "fn": run_git_credentials,
    },
    "repos": {
        "description": "List all repos — URL, provider, branch, workspace path",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [],
        "flags": [],
        "fn": run_repos_list,
    },
}
