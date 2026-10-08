"""Shared SQL statement execution helpers — used by uc, sql, attacks modules."""

import json
import time
import urllib.request


def exec_sql(w, sql: str, warehouse_id: str, timeout_s: int = 300, disposition=None):
    """Submit SQL, poll until terminal state. Returns StatementResponse."""
    kwargs = dict(statement=sql, warehouse_id=warehouse_id, wait_timeout="50s")
    if disposition is not None:
        kwargs["disposition"] = disposition
    r     = w.statement_execution.execute_statement(**kwargs)
    state = r.status.state.value if r.status and r.status.state else ""
    if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
        return r
    sid      = r.statement_id
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(5)
        r     = w.statement_execution.get_statement(statement_id=sid)
        state = r.status.state.value if r.status and r.status.state else ""
        if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
            return r
    return r


def get_rows(r) -> list:
    """Extract rows from a SUCCEEDED StatementResponse — inline or external links."""
    if not r or not r.result:
        return []
    if r.result.data_array:
        return r.result.data_array
    rows = []
    for link in (getattr(r.result, "external_links", None) or []):
        try:
            with urllib.request.urlopen(link.external_link) as resp:
                rows.extend(json.loads(resp.read().decode()))
        except Exception:
            pass
    return rows
