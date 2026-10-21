"""Render the cloud deployment report from the facts azure-report.sh collected.

Usage: python azure_report.py <facts dir> <report dir>

The facts directory holds the JSON files azure-report.sh wrote (one per `az`
query plus context.json). Two files come out: a JSON grounding, which is what the
shared agentic loop's Cloud Deployment Review mode may reason over, and the
markdown report for the technical report. Standard library only.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SECURITY_CONTROLS = [
    (
        "Endpoint",
        "Single public entry point: only the nginx proxy container app has external "
        "ingress; every Flask service is internal-only and not resolvable from the internet.",
    ),
    (
        "Endpoint",
        "HTTPS only: the public ingress redirects plain HTTP to HTTPS "
        "(allowInsecure=false) with a managed TLS certificate.",
    ),
    (
        "Endpoint",
        "Production process model: services run under gunicorn, not Flask's debug server; "
        "session cookies are HttpOnly, SameSite=Lax and Secure.",
    ),
    (
        "Data",
        "PostgreSQL Flexible Server is VNet-injected with public network access disabled; "
        "clients connect with sslmode=require. Automatic backups are retained for 7 days.",
    ),
    (
        "Data",
        "Every secret (database URLs, Flask secret keys, inter-service token) lives in Key "
        "Vault (RBAC); container apps read them with a user-assigned managed identity. "
        "Nothing is stored in the repository, the workflow or GitHub secrets.",
    ),
    (
        "Data",
        "Container Registry: admin user disabled, images pulled with the managed identity.",
    ),
    (
        "Data",
        "Plant-image storage: HTTPS/TLS 1.2 only, no public blob access, network access "
        "limited to the apps subnet.",
    ),
    (
        "Pipeline",
        "GitHub Actions authenticates to Azure with OpenID Connect federation scoped to one "
        "resource group; no cloud credential is stored in GitHub.",
    ),
]


def load(directory: Path, name: str):
    path = directory / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def value(outputs: dict | None, key: str, default="?"):
    if not outputs or key not in outputs:
        return default
    return outputs[key].get("value", default)


def table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def main(facts_dir: str, report_dir: str) -> int:
    facts = Path(facts_dir)
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)

    context = load(facts, "context") or {}
    platform = load(facts, "platform") or {}
    apps = load(facts, "apps") or {}
    container_apps = load(facts, "containerapps") or []
    postgres = load(facts, "postgres") or []
    keyvaults = load(facts, "keyvault") or []
    storage = load(facts, "storage") or []
    resources = load(facts, "resources") or []

    generated = context.get("generated_at") or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    stamp = generated.replace("-", "").replace(":", "")
    app_url = value(apps, "appUrl")
    baseline = context.get("cloud_baseline", {})
    smoke = context.get("smoke_result", "unknown")

    grounding = {
        "report": "cloud-deployment",
        "generated_at": generated,
        "deployment": {
            "platform": context.get("platform", "Microsoft Azure"),
            "subscription": context.get("subscription"),
            "resource_group": context.get("resource_group"),
            "location": context.get("location"),
            "commit": context.get("commit"),
            "branch": context.get("branch"),
            "image_tag": context.get("image_tag"),
            "actor": context.get("actor"),
            "workflow_run_url": context.get("workflow_run_url") or None,
        },
        "endpoints": {
            "app_url": app_url,
            "public_urls": value(apps, "publicUrls", {}),
            "internal_fqdns": value(apps, "internalFqdns", {}),
        },
        "cloud_baseline": baseline,
        "smoke_test": {"result": smoke},
        "container_apps": container_apps,
        "postgres": postgres,
        "key_vaults": keyvaults,
        "storage_accounts": storage,
        "resources": resources,
        "platform_outputs": {k: v.get("value") for k, v in platform.items()},
        "security_controls": [{"area": a, "control": c} for a, c in SECURITY_CONTROLS],
    }

    flags = table(
        ["Service", "Required cloud baseline", "Deployed value"],
        [
            ["AI-Mode (Ollama)", "disabled", "disabled" if not baseline.get("ai_mode_enabled") else "ENABLED (bonus)"],
            ["MCP Server", "disabled", "disabled" if not baseline.get("mcp_enabled") else "ENABLED (bonus)"],
            ["RAG Server", "disabled", "disabled" if not baseline.get("rag_enabled") else "ENABLED (bonus)"],
            ["Multi-Agent Server", "disabled", "disabled" if not baseline.get("multi_agent_enabled") else "ENABLED (bonus)"],
        ],
    )
    apps_table = table(
        ["Container app", "Ingress", "Image", "Revision", "Status", "Replicas"],
        [
            [
                a.get("name"),
                "public HTTPS" if a.get("external") else "internal",
                (a.get("image") or "").split("/", 1)[-1],
                a.get("revision"),
                a.get("status"),
                f"{a.get('minReplicas')}-{a.get('maxReplicas')}",
            ]
            for a in sorted(container_apps, key=lambda a: str(a.get("name")))
        ],
    )
    db_table = table(
        ["Server", "Version", "SKU", "Public access", "Backups"],
        [
            [p.get("name"), p.get("version"), f"{p.get('tier')} {p.get('sku')}", p.get("publicNetworkAccess"), f"{p.get('backupRetentionDays')} days"]
            for p in postgres
        ],
    )
    controls = table(["Area", "Control"], [[a, c] for a, c in SECURITY_CONTROLS])
    resource_rows = sorted(
        ((r.get("type", "").split("/", 1)[-1], r.get("name")) for r in resources),
        key=lambda r: (r[0], str(r[1])),
    )
    resource_table = table(["Type", "Name"], [list(r) for r in resource_rows])
    run_url = context.get("workflow_run_url") or "(run locally)"
    public_urls = value(apps, "publicUrls", {}) or {}

    md = f"""# Cloud deployment report — Microsoft Azure

Generated {generated} by `scripts/deploy/azure-report.sh`.

## Deployment

| | |
|---|---|
| Platform | {context.get("platform", "Microsoft Azure")} (Azure Container Apps + Azure Database for PostgreSQL) |
| Subscription | {context.get("subscription")} |
| Resource group | `{context.get("resource_group")}` ({context.get("location")}) |
| Commit | `{context.get("commit")}` on `{context.get("branch")}` |
| Image tag | `{context.get("image_tag")}` |
| Triggered by | {context.get("actor")} |
| Workflow run | {run_url} |
| Smoke test | **{str(smoke).upper()}** (`scripts/deploy/azure-smoke.sh`) |

## Access

| Feature | URL |
|---|---|
| Frontend | {app_url} |
| Auth | {public_urls.get("auth", "?")} |
| Virtual Garden | {public_urls.get("vgarden", "?")} |
| Plant Almanac | {public_urls.get("almanac", "?")} |
| Plant Health | {public_urls.get("health", "?")} |

## Cloud baseline (Assessment 3 requirement)

{flags}

The frontend UI, backend/API services, database and CRUD functions run without any
model, MCP, RAG or Multi-Agent call. The switches are parameters of `infra/apps.bicep`;
the optional bonus profile is the only thing that turns them on.

## Container apps

{apps_table}

## Database

{db_table}

One database per service on the shared server: `auth`, `vgarden`, `health`, `almanac`.
Schema migrations run on start-up (Flask-Migrate / Alembic), as locally.

## Security controls

{controls}

## Resources in the resource group

{resource_table}

## Final human release decision

To be completed by the team after reviewing this report and the agentic loop's
Cloud Deployment Review output:

- [ ] **Approved** — release stands
- [ ] **Approved with corrections** (list):
- [ ] **Rejected** — roll back / redeploy (reason):

Reviewer: ______________________  Date: ____________
"""

    json_path = out / f"cloud-deployment-{stamp}.json"
    md_path = out / f"cloud-deployment-{stamp}.md"
    json_path.write_text(json.dumps(grounding, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    shutil.copyfile(json_path, out / "latest.json")
    shutil.copyfile(md_path, out / "latest.md")
    print(f"report: {md_path}")
    print(f"grounding: {json_path}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(md)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
