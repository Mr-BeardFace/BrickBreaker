"""MODULES registry — assembled from all module COMMANDS dicts"""

from bb.modules import (
    identity, secrets, compute, jobs, workspace,
    uc, sql, serving, dbfs, settings, imds, persist, recon,
)

MODULES: dict = {
    "identity": {
        "description": "Users, groups, service principals, tokens, access control",
        "commands": identity.COMMANDS,
    },
    "secrets": {
        "description": "Secret scopes and key names (values require cluster execution)",
        "commands": secrets.COMMANDS,
    },
    "compute": {
        "description": "Clusters, init scripts, instance profiles, command execution",
        "commands": compute.COMMANDS,
    },
    "jobs": {
        "description": "Job configs, spark env vars, git source",
        "commands": jobs.COMMANDS,
    },
    "workspace": {
        "description": "Notebooks, files, git credentials, repos",
        "commands": workspace.COMMANDS,
    },
    "uc": {
        "description": "Unity Catalog — catalogs, schemas, tables, connections, credentials",
        "commands": uc.COMMANDS,
    },
    "sql": {
        "description": "Warehouses, saved queries, query history, statement execution",
        "commands": sql.COMMANDS,
    },
    "serving": {
        "description": "Model serving endpoints and container logs",
        "commands": serving.COMMANDS,
    },
    "dbfs": {
        "description": "DBFS file browser and reader",
        "commands": dbfs.COMMANDS,
    },
    "settings": {
        "description": "Workspace config, compliance profile, notification destinations",
        "commands": settings.COMMANDS,
    },
    "imds": {
        "description": "Cloud lateral movement via IMDS (requires --aggressive)",
        "commands": imds.COMMANDS,
    },
    "persist": {
        "description": "Persistence — create PATs, OBO tokens, service principals",
        "commands": persist.COMMANDS,
    },
    "recon": {
        "description": "Cross-module composite commands",
        "commands": recon.COMMANDS,
    },
}
