"""WorkspaceClient factory"""

import sys
from bb.core.config import get_profile_config, PROFILES_FILE


def make_client(profile_name: str, override_host: str = None, override_token: str = None):
    from databricks.sdk import WorkspaceClient
    from bb.core.display import console

    cfg   = get_profile_config(profile_name)
    host  = override_host  or cfg.get("host", "")
    token = override_token or cfg.get("token", "")
    if not host or not token:
        console.print(f"[red]Profile '{profile_name}' missing host or token — edit {PROFILES_FILE}[/red]")
        sys.exit(1)
    return WorkspaceClient(host=host, token=token)
