"""Identity module — users, groups, service principals, tokens, access control"""

import json

from bb.core.db import now_iso, log_pull, fmt_epoch_ms, should_use_cache
from bb.core.display import console, next_step
from bb.core.flags import limit
from rich import box
from rich.table import Table


def run_whoami(w, conn, profile, flags):
    console.print("\n[bold]Current Identity[/bold]\n")
    try:
        me           = w.current_user.me()
        groups       = [g.display or str(g.value) for g in (me.groups or [])]
        entitlements = [e.value for e in (me.entitlements or [])]
        emails       = ", ".join(e.value for e in (me.emails or []) if e.value)
        is_admin     = "admins" in groups or any("admin" in g.lower() for g in groups)

        t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        t.add_column("Field", style="dim", min_width=18)
        t.add_column("Value")
        t.add_row("Username",     me.user_name    or "?")
        t.add_row("Display Name", me.display_name or "?")
        t.add_row("Email",        emails           or "?")
        t.add_row("Admin",        "[red]YES[/red]" if is_admin else "[green]No[/green]")
        t.add_row("Groups",       ", ".join(groups)       if groups       else "(none)")
        t.add_row("Entitlements", ", ".join(entitlements) if entitlements else "(none)")
        console.print(t)
        next_step("recon attack-surface --run",
                  f"uc grants --name {me.user_name or '<username>'} --run",
                  "recon persist-check --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def _display_users_table(rows, age: str):
    console.print(f"\n[bold]Users[/bold]  [dim](cached {age})[/dim]\n")
    t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
    t.add_column("Username",     style="cyan")
    t.add_column("Display Name")
    t.add_column("Email")
    t.add_column("Groups")
    t.add_column("Admin")
    for r in rows:
        try:
            grps = json.loads(r["groups_json"] or "[]")
        except Exception:
            grps = []
        g_str = ", ".join(grps[:3]) + ("..." if len(grps) > 3 else "")
        t.add_row(r["user_name"] or "?", r["display_name"] or "?",
                  r["email"] or "?", g_str,
                  "[red]Yes[/red]" if r["is_admin"] else "")
    console.print(t)


def run_users(w, conn, profile, flags):
    module = "identity.users"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM users ORDER BY user_name").fetchall()
        _display_users_table(rows, age)
        return

    console.print("\n[bold]Users[/bold]\n")
    try:
        kwargs = {"filter": flags["filter"]} if flags["filter"] else {}
        users  = list(w.users.list(**kwargs))
        shown  = limit(users, flags["limit"])
        now    = now_iso()

        conn.execute("DELETE FROM users")
        for u in users:
            email    = next((e.value for e in (u.emails or []) if e.primary), None) or \
                       next((e.value for e in (u.emails or [])), None)
            grps     = [g.display or str(g.value) for g in (u.groups or [])]
            is_admin = int("admins" in grps or any("admin" in g.lower() for g in grps))
            conn.execute(
                "INSERT OR REPLACE INTO users VALUES (?,?,?,?,?,?,?,?)",
                (str(u.id), u.user_name, u.display_name, email,
                 json.dumps(grps), is_admin, int(bool(u.active)), now)
            )
        log_pull(conn, module, profile, len(users))
        conn.commit()

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Username",     style="cyan")
        t.add_column("Display Name")
        t.add_column("Email")
        t.add_column("Groups")
        t.add_column("Admin")
        for u in shown:
            email    = next((e.value for e in (u.emails or []) if e.primary), None) or \
                       next((e.value for e in (u.emails or [])), "?")
            grps     = [g.display or str(g.value) for g in (u.groups or [])]
            g_str    = ", ".join(grps[:3]) + ("…" if len(grps) > 3 else "")
            is_admin = "admins" in grps or any("admin" in g.lower() for g in grps)
            t.add_row(u.user_name or "?", u.display_name or "?", email or "?",
                      g_str, "[red]Yes[/red]" if is_admin else "")
        console.print(t)
        if flags["limit"] > 0 and len(users) > flags["limit"]:
            console.print(f"[dim]  {len(users)} total — showing {flags['limit']} (--limit 0 for all)[/dim]")
        next_step("uc grants --name <username> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_groups(w, conn, profile, flags):
    module = "identity.groups"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM groups ORDER BY display_name").fetchall()
        console.print(f"\n[bold]Groups[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Display Name", style="cyan")
        t.add_column("ID",           style="dim")
        t.add_column("Members",      justify="right")
        for r in rows:
            t.add_row(r["display_name"] or "?", r["id"], str(r["member_count"] or 0))
        console.print(t)
        return

    console.print("\n[bold]Groups[/bold]\n")
    try:
        kwargs = {"filter": flags["filter"]} if flags["filter"] else {}
        groups = list(w.groups.list(**kwargs))
        shown  = limit(groups, flags["limit"])
        now    = now_iso()

        conn.execute("DELETE FROM groups")
        for g in groups:
            members = g.members or []
            conn.execute(
                "INSERT OR REPLACE INTO groups VALUES (?,?,?,?,?)",
                (str(g.id), g.display_name, len(members),
                 json.dumps([m.display or str(m.value) for m in members]), now)
            )
        log_pull(conn, module, profile, len(groups))
        conn.commit()

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Display Name", style="cyan")
        t.add_column("ID",           style="dim")
        t.add_column("Members",      justify="right")
        for g in shown:
            t.add_row(g.display_name or "?", str(g.id), str(len(g.members or [])))
        console.print(t)
        if flags["limit"] > 0 and len(groups) > flags["limit"]:
            console.print(f"[dim]  {len(groups)} total — showing {flags['limit']}[/dim]")
        next_step("uc grants --name <group_display_name> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_service_principals(w, conn, profile, flags):
    module = "identity.service-principals"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM service_principals ORDER BY display_name").fetchall()
        console.print(f"\n[bold]Service Principals[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Display Name", style="cyan")
        t.add_column("App ID")
        t.add_column("ID",           style="dim")
        t.add_column("Active")
        for r in rows:
            t.add_row(r["display_name"] or "?", r["application_id"] or "?",
                      r["id"], "[green]Yes[/green]" if r["active"] else "[red]No[/red]")
        console.print(t)
        return

    console.print("\n[bold]Service Principals[/bold]\n")
    try:
        kwargs = {"filter": flags["filter"]} if flags["filter"] else {}
        sps    = list(w.service_principals.list(**kwargs))
        shown  = limit(sps, flags["limit"])
        now    = now_iso()

        conn.execute("DELETE FROM service_principals")
        for sp in sps:
            conn.execute(
                "INSERT OR REPLACE INTO service_principals VALUES (?,?,?,?,?)",
                (str(sp.id), str(sp.application_id or ""), sp.display_name,
                 int(bool(sp.active)), now)
            )
        log_pull(conn, module, profile, len(sps))
        conn.commit()

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Display Name", style="cyan")
        t.add_column("App ID")
        t.add_column("ID",           style="dim")
        t.add_column("Active")
        for sp in shown:
            t.add_row(sp.display_name or "?", str(sp.application_id or "?"),
                      str(sp.id), "[green]Yes[/green]" if sp.active else "[red]No[/red]")
        console.print(t)
        next_step("uc grants --name <sp_display_name> --run",
                  "persist create-obo-token --id <application_id> --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_tokens(w, conn, profile, flags):
    module = "identity.tokens"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM tokens ORDER BY creation_time DESC").fetchall()
        console.print(f"\n[bold]My Tokens[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Token ID",  style="dim")
        t.add_column("Comment",   style="cyan")
        t.add_column("Created")
        t.add_column("Expires")
        for r in rows:
            expires = fmt_epoch_ms(r["expiry_time"]) if r["expiry_time"] else "[green]never[/green]"
            t.add_row(r["token_id"] or "?", r["comment"] or "(no comment)",
                      fmt_epoch_ms(r["creation_time"]), expires)
        console.print(t)
        return

    console.print("\n[bold]My Tokens[/bold]  [dim](values never returned by API)[/dim]\n")
    try:
        tokens = list(w.tokens.list())
        now    = now_iso()
        conn.execute("DELETE FROM tokens")
        for tk in tokens:
            conn.execute(
                "INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?)",
                (tk.token_id, tk.comment, tk.creation_time, tk.expiry_time, now)
            )
        log_pull(conn, module, profile, len(tokens))
        conn.commit()

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Token ID",  style="dim")
        t.add_column("Comment",   style="cyan")
        t.add_column("Created")
        t.add_column("Expires")
        for tk in tokens:
            created = fmt_epoch_ms(tk.creation_time)
            expires = fmt_epoch_ms(tk.expiry_time) if tk.expiry_time else "[green]never[/green]"
            t.add_row(tk.token_id or "?", tk.comment or "(no comment)", created, expires)
        console.print(t)
        next_step("persist create-token --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_ip_access_lists(w, conn, profile, flags):
    module = "identity.ip-access-lists"
    use_cache, age = should_use_cache(conn, module, flags)
    if use_cache is None:
        console.print("[yellow]No cached data — run without --cached to pull[/yellow]")
        return
    if use_cache:
        rows = conn.execute("SELECT * FROM ip_access_lists ORDER BY label").fetchall()
        console.print(f"\n[bold]IP Access Lists[/bold]  [dim](cached {age})[/dim]\n")
        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Label",   style="cyan")
        t.add_column("Type")
        t.add_column("Enabled")
        t.add_column("IPs",     justify="right")
        t.add_column("Preview")
        for r in rows:
            try:
                ips = json.loads(r["ip_addresses"] or "[]")
            except Exception:
                ips = []
            preview = ", ".join(ips[:3]) + ("..." if len(ips) > 3 else "")
            t.add_row(r["label"] or "?", r["list_type"] or "?",
                      "[green]Yes[/green]" if r["enabled"] else "[red]No[/red]",
                      str(len(ips)), preview)
        console.print(t)
        return

    console.print("\n[bold]IP Access Lists[/bold]\n")
    try:
        lists = list(w.ip_access_lists.list())
        now   = now_iso()
        conn.execute("DELETE FROM ip_access_lists")
        for lst in lists:
            conn.execute(
                "INSERT OR REPLACE INTO ip_access_lists VALUES (?,?,?,?,?,?)",
                (lst.list_id, lst.label,
                 lst.list_type.value if lst.list_type else "?",
                 json.dumps(lst.ip_addresses or []),
                 int(bool(lst.enabled)), now)
            )
        log_pull(conn, module, profile, len(lists))
        conn.commit()

        t = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        t.add_column("Label",   style="cyan")
        t.add_column("Type")
        t.add_column("Enabled")
        t.add_column("IPs",     justify="right")
        t.add_column("Preview")
        for lst in lists:
            ips     = lst.ip_addresses or []
            preview = ", ".join(ips[:3]) + ("…" if len(ips) > 3 else "")
            t.add_row(lst.label or "?",
                      lst.list_type.value if lst.list_type else "?",
                      "[green]Yes[/green]" if lst.enabled else "[red]No[/red]",
                      str(len(ips)), preview)
        console.print(t)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "whoami": {
        "description": "Current user identity, groups, entitlements, admin status",
        "activity": ["info"], "type": "R", "noise": "Low — single API call",
        "prereqs": [], "caveats": [], "flags": [],
        "fn": run_whoami,
    },
    "users": {
        "description": "List all workspace users",
        "activity": ["info"], "type": "R", "noise": "Low — single SCIM call",
        "prereqs": [],
        "caveats": ["Non-admin may see limited results"],
        "flags": [
            ("--filter TEXT", "SCIM filter (server-side), e.g. 'displayName co admin'"),
            ("--limit N",     "Max results — default 100, 0=all"),
        ],
        "fn": run_users,
    },
    "groups": {
        "description": "List all workspace groups and member counts",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [],
        "flags": [
            ("--filter TEXT", "SCIM filter (server-side)"),
            ("--limit N",     "Max results — default 100, 0=all"),
        ],
        "fn": run_groups,
    },
    "service-principals": {
        "description": "List all service principals",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": [],
        "flags": [
            ("--filter TEXT", "SCIM filter (server-side)"),
            ("--limit N",     "Max results — default 100, 0=all"),
        ],
        "fn": run_service_principals,
    },
    "tokens": {
        "description": "List your own PAT tokens (metadata only — values never returned)",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": [], "caveats": ["Token values are only returned at creation time"],
        "flags": [],
        "fn": run_tokens,
    },
    "ip-access-lists": {
        "description": "List network IP allowlists and blocklists",
        "activity": ["info"], "type": "R", "noise": "Low",
        "prereqs": ["Admin token required"], "caveats": [],
        "flags": [],
        "fn": run_ip_access_lists,
    },
}
