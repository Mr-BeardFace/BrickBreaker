# BrickBreaker

A Databricks red team enumeration and lateral movement tool for authorized security assessments. BrickBreaker maps the attack surface of a Databricks workspace using only a PAT or OAuth token — no agent, no deployment, no persistence required.

> **For authorized use only.** Use only against environments where you have explicit written permission.

---

## What It Does

BrickBreaker enumerates Databricks workspaces across 15 attack surface areas:

- **Credentials** — secret scopes, job env vars, init scripts, UC connection options, serving endpoint env vars, notebook content
- **Cloud lateral movement** — IMDS credential extraction from running clusters (AWS STS, Azure ARM/Graph tokens), instance profiles, UC temp storage credentials (S3/ADLS)
- **Data access** — Unity Catalog topology, table metadata, temporary table/path credentials that bypass audit logging, SQL execution
- **Identity** — users, groups, service principals, token inventory, IP access lists, grants
- **Persistence** — PAT creation, OBO token generation, service principal creation

Commands are tiered by impact and reversibility so you know exactly what each one does before running it.

---

## Installation

```bash
git clone https://github.com/Mr-BeardFace/BrickBreaker.git
cd BrickBreaker
pip install -r requirements.txt
```

**Requirements:** Python 3.10+, `databricks-sdk >= 0.20.0`, `rich >= 13.0.0`, `cryptography >= 41.0.0`

---

## Quick Start

**1. Add a profile (stores credentials locally in `~/.brickbreaker/<profile>.ini`):**

```bash
python brickbreaker.py profile add
```

You will be prompted for a workspace host and PAT. Credentials are stored in plaintext locally — treat the profile directory accordingly.

**2. Explore the workspace:**

```bash
# Who am I and what can I do?
python brickbreaker.py recon whoami --run

# Full attack surface probe
python brickbreaker.py recon attack-surface --run

# Passive credential sweep
python brickbreaker.py recon cred-hunt --run
```

**3. Follow the `↳` hints** — every command that returns results shows follow-up commands matched to what was found.

---

## Command Structure

```
python brickbreaker.py <module> <command> [--flags] --run
```

- `--run` executes the command (omit to see the info pane with description, flags, noise level)
- `--cached` reads from local SQLite cache instead of hitting the API
- `--fresh` forces a fresh pull even if cached data is recent
- `--aggressive` enables EXEC-tier operations (cluster code execution)
- `--extended` removes truncation on large result sets (groups, tasks, IPs, rows)
- `--simulate` submits SQL but forces `EXTERNAL_LINKS` disposition — row data never enters memory; does a Range GET (1 byte) on the first S3 chunk to log access in CloudTrail without downloading data
- `--rows N` fetches N sample rows from a table (requires `--warehouse`)
- `--output <file>` tees all output to a plain-text file in addition to the terminal
- `--limit N` caps results (default 100; `0` = all)

**View all modules:**

```bash
python brickbreaker.py
```

**View all commands in a module:**

```bash
python brickbreaker.py recon
```

**View command info pane (no execution):**

```bash
python brickbreaker.py secrets list
```

---

## Execution Tiers

Every command is labeled with an execution tier visible in its info pane:

| Tier | Meaning |
|------|---------|
| **R** | Read-only API call — no side effects, safe to run |
| **R\*** | Client-side computation over pulled data — multiple API calls, higher noise |
| **W** | Write operation — creates or modifies workspace objects (prompts for confirmation) |
| **EXEC** | Executes code on a cluster — requires `--aggressive` flag, visible in cluster event log |

---

## Activity Tags

| Tag | What it signals |
|-----|----------------|
| `cred` | May return credentials or secrets |
| `latm` | Lateral movement path (cloud IAM roles, storage credentials) |
| `data` | Direct data access |
| `info` | Enumeration only |
| `persist` | Creates artifacts that persist after the session |

---

## Module Reference

### `identity` — Users, groups, service principals, tokens, access control

| Command | Type | Description |
|---------|------|-------------|
| `whoami` | R | Current identity, groups, entitlements, admin status |
| `users` | R | All workspace users |
| `groups` | R | All groups and member counts |
| `service-principals` | R | All service principals |
| `tokens` | R | Your own PAT tokens (metadata only) |
| `ip-access-lists` | R | Network IP allowlists and blocklists |

---

### `secrets` — Secret scopes and key names

| Command | Type | Description |
|---------|------|-------------|
| `scopes` | R | All secret scopes and backend types |
| `list` | R | Key names in a scope (`--scope`) |
| `all` | R | All scopes + all accessible key names in one pass |
| `get` | EXEC | Extract one secret value via cluster execution (`--scope`, `--id`, `--cluster`) |
| `dump` | EXEC | Extract all accessible secrets across all scopes (`--cluster`) |

> Secret values are never returned by the REST API. `get` and `dump` require a running cluster and `--aggressive`.

---

### `compute` — Clusters, init scripts, instance profiles, command execution

| Command | Type | Description |
|---------|------|-------------|
| `clusters` | R | Running clusters — owner, instance profile, auto-termination window |
| `cluster-get` | R | Full cluster config — spark env vars, instance profile, init scripts (`--id`) |
| `create-cluster` | W | Spin up a single-node cluster on latest LTS — auto-terminates in 30 min |
| `delete-cluster` | W | Permanently delete a cluster (`--cluster`) |
| `init-scripts-list` | R | Global init scripts (IDs and names) |
| `init-script-get` | R | Full init script content, base64 decoded (`--id`) |
| `instance-profiles` | R | IAM role ARNs registered for cluster attachment (AWS) |
| `execute` | EXEC | Run arbitrary code on a running cluster (`--cluster`, `--sql`) |

---

### `jobs` — Job configs, spark env vars, git source

| Command | Type | Description |
|---------|------|-------------|
| `list` | R | All jobs — IDs, names, creator, schedule |
| `get` | R | Full job config — spark env vars, task params, git source, libraries (`--id`) |
| `run` | W | Trigger a job run now (`--id`) — returns run ID |

> Serverless jobs store credentials in `notebook_task.base_parameters`. `jobs get` checks both `spark_env_vars` and task params.

---

### `workspace` — Notebooks, files, git credentials, repos

| Command | Type | Description |
|---------|------|-------------|
| `list` | R | List workspace items at a path (`--path`, `--depth`) |
| `export` | R | Export a notebook or file source (`--path`) — content cached for `loot scan` |
| `git-credentials` | R | Git credential entries (usernames + providers — no token values) |
| `repos` | R | All repos — URL, provider, branch, workspace path |

---

### `uc` — Unity Catalog

| Command | Type | Description |
|---------|------|-------------|
| `catalogs` | R | All catalogs |
| `schemas` | R | Schemas in a catalog (`--catalog`) |
| `tables` | R | Tables in a schema — name, type, storage location (`--catalog`, `--schema`) |
| `table-meta` | R | Column list and row count (`--id`; `--rows N` pulls sample rows; `--simulate` submits query without downloading) |
| `schema-meta` | R | All tables with column counts and row counts (`--catalog`, `--schema`; `--simulate` skips COUNT queries) |
| `external-locations` | R | External storage locations and credential bindings |
| `storage-credentials` | R | Storage credential objects (IAM roles / service principals) |
| `connections` | R | Connection names and types (no credential values) |
| `connections-get` | R | Full connection config — options may include credentials (`--name`) |
| `connections-all` | R | Full options for all connections in one pass |
| `grants` | R | Grants on an object (`--id`) or grants to a principal (`--name`, R\*) |
| `metastore` | R | Metastore ID, cloud, region, storage root |
| `volumes` | R | Volumes in a schema (`--catalog`, `--schema`) |
| `temp-path-creds` | R | Temporary STS/SAS credentials for an external location URL (`--path`) |
| `temp-table-creds` | R | Direct storage credentials for a table's underlying files (`--id`) |

> `temp-table-creds` bypasses Databricks SQL audit logging — access goes directly to S3/ADLS.

---

### `sql` — Warehouses, saved queries, query history, execution

| Command | Type | Description |
|---------|------|-------------|
| `warehouses` | R | All SQL warehouses — ID, size, state, creator |
| `queries` | R | Saved queries (IDs and names) |
| `queries-get` | R | Full saved query text (`--id`) |
| `query-history` | R | Recent query history with user, time, status, preview |
| `execute` | R | Run SQL against a warehouse (`--warehouse`, `--sql`); add `--simulate` to submit without pulling data |

---

### `serving` — Model serving endpoints

| Command | Type | Description |
|---------|------|-------------|
| `list` | R | All serving endpoints — name, state, creator |
| `get` | R | Full endpoint config — served models, environment variables (`--name`) |
| `logs` | R | Container logs for a served model — may leak secrets (`--name`, `--model`) |

---

### `dbfs` — DBFS file browser and reader

| Command | Type | Description |
|---------|------|-------------|
| `list` | R | List DBFS path contents (`--path`, `--depth`) |
| `read` | R | Read a DBFS file (`--path`) |
| `shell` | R | Interactive DBFS shell — `ls`, `cd`, `cat`, `get`, `find`, `grep` |

---

### `settings` — Workspace configuration

| Command | Type | Description |
|---------|------|-------------|
| `dump` | R | Workspace config, compliance profile, notification destinations |

---

### `imds` — Cloud credential extraction via cluster IMDS

All IMDS commands require `--aggressive` and a running cluster ID.

| Command | Type | Description |
|---------|------|-------------|
| `aws` | EXEC | AWS STS credentials from cluster IMDS (IMDSv2) (`--cluster`) |
| `azure-arm` | EXEC | Azure ARM bearer token from managed identity (`--cluster`) |
| `azure-graph` | EXEC | Azure Graph bearer token from managed identity (`--cluster`) |

---

### `persist` — Persistence operations

All persist commands are type **W** (write) and prompt for confirmation.

| Command | Type | Description |
|---------|------|-------------|
| `create-token` | W | Create a PAT for the current identity |
| `create-obo-token` | W | Create OBO token for a service principal — admin only (`--id`) |
| `create-service-principal` | W | Create a new service principal (`--name`) |

---

### `loot` — Aggregated findings from local cache

Read-only views over the local SQLite cache — no API calls. Run after enumeration commands to review everything in one place.

| Command | Type | Description |
|---------|------|-------------|
| `dump` | R\* | All cached high-value findings — secrets, job env vars (decrypted), UC connections, storage creds, git credentials, IAM instance profiles, saved queries, exported notebooks, tokens |
| `scan` | R\* | Regex credential pattern scanner across all cached data — AWS keys, PATs, GitHub tokens, Azure secrets, Slack webhooks, and more |

> Sensitive values (job env vars, UC connection options, init script content, notebook content) are stored **encrypted at rest** using Fernet symmetric encryption. Per-profile keys live at `~/.brickbreaker/<profile>.key`.

> `recon cred-hunt` writes all fetched job configs and query text to the cache, so `loot dump` reflects the full sweep without re-running individual `jobs get` commands.

---

### `attacks` — Offensive simulation scenarios

| Command | Type | Description |
|---------|------|-------------|
| `smash-grab` | R | Simulate full-workspace data exfil — `SELECT *` every accessible table, no data pulled |

`smash-grab` requires `--aggressive` and `--warehouse`. For each table it:
1. Submits `SELECT *` with `EXTERNAL_LINKS` disposition — Databricks writes results to a temp S3 prefix; row data never enters memory
2. Reads row count and column schema from the statement manifest (already in the API response)
3. Issues a Range GET (`bytes=0-0`) on the first S3 chunk — downloads 1 byte, logs a `GetObject` in CloudTrail under the same account that ran the query

The result is a correlated artifact pair: Databricks audit log entry + S3 CloudTrail entry, proving an attacker with these credentials could have exfiltrated the data.

```bash
# Full workspace
python brickbreaker.py attacks smash-grab --warehouse <id> --aggressive --run

# Narrow scope
python brickbreaker.py attacks smash-grab --warehouse <id> --catalog main --aggressive --run

# Exclude noisy system catalogs
python brickbreaker.py attacks smash-grab --warehouse <id> \
  --exclude-catalog system,samples --aggressive --run

# Exclude by schema as well
python brickbreaker.py attacks smash-grab --warehouse <id> \
  --exclude-catalog system --exclude-schema information_schema --aggressive --run
```

---

### `recon` — Cross-module composite commands

| Command | Type | Description |
|---------|------|-------------|
| `whoami` | R | Identity + capability probe across ~7 API calls |
| `attack-surface` | R | Blast radius assessment — probes all modules with current token |
| `cloud-pivot` | R | Running clusters with instance profiles — IMDS prerecon |
| `cred-hunt` | R/EXEC | Tiered passive credential sweep (init scripts → jobs → connections → notebooks) |
| `search` | R\* | Custom regex search across notebooks, queries, job params, init scripts (`--filter`) |
| `data-map` | R\* | Unity Catalog topology — catalogs, schemas, tables, external locations |
| `persist-check` | R | Read-only probe of available persistence options with follow-up commands |

**`recon cred-hunt` tiers:**

| Flag | Scope |
|------|-------|
| _(none)_ | Init scripts + job env vars/task params + UC connections |
| `--extended` | + saved SQL queries + serving endpoint env vars |
| `--aggressive` | + full recursive notebook content export and scan |

---

## Caching

BrickBreaker caches all pull results in a per-profile SQLite database at `~/.brickbreaker/<profile>.db`. Sensitive values (job spark env vars, UC connection options, init script content, exported notebook content) are encrypted at rest using Fernet symmetric encryption. The per-profile key is stored at `~/.brickbreaker/<profile>.key` — keep this directory private.

```bash
# Use cached data (no API calls)
python brickbreaker.py identity users --cached

# Force fresh pull
python brickbreaker.py identity users --fresh --run

# Default: use cache if < 4 hours old, otherwise pull fresh
python brickbreaker.py identity users --run
```

---

## Profile Management

```bash
# Add a profile
python brickbreaker.py profile add

# List profiles
python brickbreaker.py profile list

# Use a specific profile
python brickbreaker.py --profile prod recon whoami --run
```

---

## Output to File

Any command that produces content output supports `--output`:

```bash
python brickbreaker.py workspace export --path /path/to/notebook --output notebook.py --run
python brickbreaker.py compute init-script-get --id abc123 --output init.sh --run
python brickbreaker.py secrets dump --cluster abc-123 --aggressive --output secrets.txt --run
```

---

## Typical Assessment Flow

```bash
# 1. Establish identity and blast radius
python brickbreaker.py recon whoami --run
python brickbreaker.py recon attack-surface --run

# 2. Passive credential sweep — caches all job configs and query text automatically
python brickbreaker.py recon cred-hunt --run
python brickbreaker.py recon cred-hunt --extended --run

# 3. Review everything found in one place
python brickbreaker.py loot dump --run
python brickbreaker.py loot scan --run

# 4. Enumerate high-value targets
python brickbreaker.py secrets all --run
python brickbreaker.py compute clusters --run
python brickbreaker.py uc external-locations --run

# 5. Scan notebook content for hardcoded credentials
python brickbreaker.py recon cred-hunt --aggressive --run
# or export individual notebooks:
python brickbreaker.py workspace export --path /path/to/notebook --run
python brickbreaker.py loot scan --run

# 6. Cloud pivot (requires running cluster)
python brickbreaker.py recon cloud-pivot --run
python brickbreaker.py imds aws --cluster <cluster_id> --aggressive --run

# 7. Extract secrets (requires running cluster)
python brickbreaker.py secrets dump --cluster <cluster_id> --aggressive --run

# 8. Data access — direct storage credentials
python brickbreaker.py uc temp-path-creds --path s3://bucket/path --run
python brickbreaker.py uc temp-table-creds --id catalog.schema.table --run

# 9. Assess persistence options
python brickbreaker.py recon persist-check --run

# 10. Smash & grab simulation — proves data exfil without pulling data
python brickbreaker.py attacks smash-grab --warehouse <warehouse_id> \
  --exclude-catalog system,samples --aggressive --output smash-grab.txt --run
# Result: Databricks audit log + S3 CloudTrail GetObject entries proving access
```

---

## Legal

BrickBreaker is intended for use by security professionals conducting authorized penetration tests and red team assessments. Unauthorized use against systems you do not have explicit permission to test is illegal. The authors assume no liability for misuse.
