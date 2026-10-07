"""DBFS module — file browser, reader, interactive shell"""

import base64
import posixpath
import shlex

from bb.core.db import now_iso, log_pull, should_use_cache
from bb.core.display import console, write_output, next_step
from rich import box
from rich.table import Table


def run_list(w, conn, profile, flags):
    path   = flags.get("path") or "/"
    depth  = flags.get("depth", 0)
    module = f"dbfs.list:{path}:d{depth}"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute(
            "SELECT * FROM dbfs_files WHERE path LIKE ? ORDER BY path",
            (path.rstrip("/") + "%",)
        ).fetchall()
        console.print(f"\n[bold]DBFS[/bold]  [dim]{path}[/dim]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        t.add_column("", min_width=2)
        t.add_column("Path", style="cyan")
        t.add_column("Size", justify="right", style="dim")
        for r in rows:
            icon = "📁" if r["is_dir"] else "📄"
            size = _fmt_size(r["file_size"]) if not r["is_dir"] else ""
            t.add_row(icon, r["path"], size)
        console.print(t)
        return

    now = now_iso()
    console.print(f"\n[bold]DBFS[/bold]  [dim]{path}[/dim]  "
                  f"[dim]depth={'unlimited' if depth < 0 else depth}[/dim]\n")
    count = _list_recursive(w, path, depth, 0, conn, now)
    log_pull(conn, module, profile, count)
    conn.commit()
    next_step("dbfs read --path <path> --run",
              "dbfs read --path <path> --output <file> --run")


def _list_recursive(w, path: str, max_depth: int, current: int, conn=None, now: str = "") -> int:
    try:
        items = list(w.dbfs.list(path=path))
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")
        return 0

    t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    t.add_column("", min_width=2)
    t.add_column("Path",  style="cyan")
    t.add_column("Size",  justify="right", style="dim")
    count = 0
    for item in items:
        indent = "  " * current
        is_dir = item.is_dir
        size   = _fmt_size(item.file_size) if not is_dir else ""
        icon   = "📁" if is_dir else "📄"
        t.add_row(f"{indent}{icon}", item.path or "?", size)
        if conn and now:
            conn.execute(
                "INSERT OR REPLACE INTO dbfs_files VALUES (?,?,?,?)",
                (item.path, int(bool(is_dir)), item.file_size or 0, now)
            )
        count += 1
    console.print(t)

    if max_depth != 0:
        for item in items:
            if item.is_dir:
                if max_depth < 0 or current < max_depth:
                    count += _list_recursive(w, item.path, max_depth, current + 1, conn, now)
    return count


def run_read(w, conn, profile, flags):
    path = flags.get("path") or flags.get("id")
    if not path:
        path = input("DBFS path (from: dbfs list --run): ").strip()
    console.print(f"\n[bold]Read[/bold]  [dim]{path}[/dim]\n")
    console.print("[dim]  Note: file content is downloaded through the API[/dim]\n")
    try:
        CHUNK = 1048576  # 1MB
        offset = 0
        buf    = []
        while True:
            chunk = w.dbfs.read(path=path, offset=offset, length=CHUNK)
            data  = base64.b64decode(chunk.data or "")
            if not data:
                break
            buf.append(data)
            offset += len(data)
            if len(data) < CHUNK:
                break
        content = b"".join(buf).decode("utf-8", errors="replace")
        write_output(content, flags)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_shell(w, conn, profile, flags):
    """Interactive DBFS shell"""
    console.print("\n[bold]DBFS Shell[/bold]  [dim]type 'help' for commands, 'exit' to quit[/dim]\n")

    cwd = "/"

    def prompt():
        return f"dbfs:{cwd}> "

    try:
        import readline
        _setup_completion(w, cwd)
    except ImportError:
        pass

    while True:
        try:
            line = input(prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]exit[/dim]")
            break

        if not line:
            continue

        try:
            parts = shlex.split(line)
        except ValueError as e:
            console.print(f"[red]Parse error: {e}[/red]")
            continue

        cmd = parts[0].lower() if parts else ""

        if cmd in ("exit", "quit"):
            break

        elif cmd == "help":
            console.print(
                "  ls [path]             list directory\n"
                "  cd <path>             change directory\n"
                "  cat <path>            read file content  [dim](downloads via API)[/dim]\n"
                "  get <remote> [local]  download file\n"
                "  find <pattern>        find files by name pattern  [dim](lists only)[/dim]\n"
                "  pwd                   print working directory\n"
                "  grep <pattern>        grep across files  [yellow][downloads all files][/yellow]\n"
                "  exit                  quit shell"
            )

        elif cmd == "pwd":
            console.print(cwd)

        elif cmd == "ls":
            target = parts[1] if len(parts) > 1 else cwd
            target = _resolve(cwd, target)
            try:
                items = list(w.dbfs.list(path=target))
                for item in items:
                    size = _fmt_size(item.file_size) if not item.is_dir else "<DIR>"
                    name = posixpath.basename(item.path or "")
                    console.print(f"  {size:>10}  {name}")
            except Exception as e:
                console.print(f"[red]{e}[/red]")

        elif cmd == "cd":
            if len(parts) < 2:
                cwd = "/"
            else:
                target = _resolve(cwd, parts[1])
                try:
                    w.dbfs.get_status(path=target)
                    cwd = target
                except Exception as e:
                    console.print(f"[red]{e}[/red]")

        elif cmd == "cat":
            if len(parts) < 2:
                console.print("[red]cat <path>[/red]")
                continue
            path = _resolve(cwd, parts[1])
            try:
                content = _read_full(w, path)
                console.print(content)
            except Exception as e:
                console.print(f"[red]{e}[/red]")

        elif cmd == "get":
            if len(parts) < 2:
                console.print("[red]get <remote> [local][/red]")
                continue
            remote = _resolve(cwd, parts[1])
            local  = parts[2] if len(parts) > 2 else posixpath.basename(remote)
            try:
                content = _read_full_bytes(w, remote)
                with open(local, "wb") as f:
                    f.write(content)
                console.print(f"  saved → {local}  ({_fmt_size(len(content))})")
            except Exception as e:
                console.print(f"[red]{e}[/red]")

        elif cmd == "find":
            pattern = parts[1] if len(parts) > 1 else ""
            try:
                _find(w, cwd, pattern)
            except Exception as e:
                console.print(f"[red]{e}[/red]")

        elif cmd == "grep":
            if len(parts) < 2:
                console.print("[red]grep <pattern> [path][/red]")
                continue
            pattern  = parts[1]
            gpath    = _resolve(cwd, parts[2]) if len(parts) > 2 else cwd
            # Count files first
            try:
                items = [i for i in w.dbfs.list(path=gpath) if not i.is_dir]
                console.print(f"[yellow]  ⚠ grep requires downloading {len(items)} file(s). Continue? [y/N][/yellow]",
                              end=" ")
                confirm = input().strip().lower()
                if confirm != "y":
                    continue
                import re
                pat = re.compile(pattern, re.IGNORECASE)
                for item in items:
                    try:
                        text = _read_full(w, item.path)
                        for i, line in enumerate(text.splitlines(), 1):
                            if pat.search(line):
                                console.print(f"  [cyan]{item.path}[/cyan]:{i}: {line}")
                    except Exception:
                        pass
            except Exception as e:
                console.print(f"[red]{e}[/red]")

        else:
            console.print(f"[red]Unknown command: {cmd}[/red]")


def _resolve(cwd: str, path: str) -> str:
    if path.startswith("/"):
        return posixpath.normpath(path)
    return posixpath.normpath(posixpath.join(cwd, path))


def _read_full(w, path: str) -> str:
    return _read_full_bytes(w, path).decode("utf-8", errors="replace")


def _read_full_bytes(w, path: str) -> bytes:
    CHUNK  = 1048576
    offset = 0
    buf    = []
    while True:
        chunk = w.dbfs.read(path=path, offset=offset, length=CHUNK)
        data  = base64.b64decode(chunk.data or "")
        if not data:
            break
        buf.append(data)
        offset += len(data)
        if len(data) < CHUNK:
            break
    return b"".join(buf)


def _find(w, path: str, pattern: str):
    import fnmatch
    try:
        items = list(w.dbfs.list(path=path))
    except Exception:
        return
    for item in items:
        name = posixpath.basename(item.path or "")
        if not pattern or fnmatch.fnmatch(name, pattern):
            console.print(f"  {item.path}")
        if item.is_dir:
            _find(w, item.path, pattern)


def _setup_completion(w, cwd: str):
    import readline

    def completer(text, state):
        try:
            parent = posixpath.dirname(text) or cwd
            prefix = posixpath.basename(text)
            items  = w.dbfs.list(path=parent)
            names  = [posixpath.basename(i.path) for i in items
                      if posixpath.basename(i.path or "").startswith(prefix)]
            if state < len(names):
                return names[state]
        except Exception:
            pass
        return None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")


def _fmt_size(size) -> str:
    if not size:
        return "0 B"
    size = int(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


COMMANDS = {
    "list": {
        "description": "List DBFS path contents",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["--depth -1 = unlimited recursion"],
        "flags": [
            ("--path PATH", "DBFS path (default: /)"),
            ("--depth N",   "Recursion depth — 0=current dir only, -1=unlimited"),
        ],
        "fn": run_list,
    },
    "read": {
        "description": "Read a DBFS file (downloads through API)",
        "activity": ["data"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["Downloads file content through API — not a server-side operation"],
        "flags": [("--path PATH", "DBFS file path"), ("--output FILE", "Save content to file")],
        "required_flags": ["--path"],
        "fn": run_read,
    },
    "shell": {
        "description": "Interactive DBFS shell — ls, cd, cat, get, find, grep",
        "activity": ["info", "data"], "type": "R", "noise": "Low",
        "prereqs": [],
        "caveats": ["grep downloads file content to search locally"],
        "flags": [],
        "fn": run_shell,
    },
}
