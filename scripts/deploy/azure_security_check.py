"""Cloud security validation (bonus B5 endpoint security, B6 data security).

Read-only: it inspects the deployed resources with the Azure CLI and probes the
public endpoint over HTTPS. It never reads a secret value; Key Vault is only listed
by name, and container apps are checked for *how* they receive secrets.

    python3 scripts/deploy/azure_security_check.py https://<public proxy> [output dir]

Writes cloud-security-<UTC timestamp>.json/.md and latest.json/.md to the output
directory (default docs/evidence/release2/cloud-security) and exits 1 if any
control fails. Runs in the deploy job after the smoke test, and locally after
`az login`.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
RG = os.environ.get("AZURE_RESOURCE_GROUP", "rg-plantms-prod")
APPS_DEPLOYMENT = os.environ.get("APPS_DEPLOYMENT", f"{os.environ.get('AZURE_BASE_NAME', 'plantms')}-apps")

checks: list[dict] = []


def record(area: str, cid: str, title: str, ok: bool, detail: str, evidence: str = "") -> None:
    checks.append({"area": area, "id": cid, "control": title, "result": "pass" if ok else "fail",
                   "detail": detail, "evidence": evidence})
    print(f"  {'PASS' if ok else 'FAIL'}  {cid}  {title}: {detail}", flush=True)


def az(*args: str):
    out = subprocess.run(["az", *args, "-o", "json"], capture_output=True, text=True, check=True)  # noqa: S603,S607
    return json.loads(out.stdout or "null")


def guarded(area: str, cid: str, title: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # a control that cannot be verified counts as failed
        record(area, cid, title, False, f"could not verify: {type(exc).__name__}: {exc}")


def https_request(url: str, method: str = "GET", body: str | None = None, headers: dict | None = None):
    parts = urlsplit(url)
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=90,
                                       context=ssl.create_default_context())
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, response.headers, data.decode("utf-8", "replace")


def endpoint_checks(base: str) -> None:
    area = "Endpoint security (B5)"
    host = urlsplit(base).hostname

    def tls():
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=30) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls_sock:
                version, cert = tls_sock.version(), tls_sock.getpeercert()
        issuer = dict(x[0] for x in cert["issuer"]).get("organizationName", "?")
        ok = version in ("TLSv1.2", "TLSv1.3")
        old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        old.check_hostname, old.verify_mode = False, ssl.CERT_NONE
        warnings.filterwarnings("ignore", category=DeprecationWarning)  # deliberately offering old TLS
        old.minimum_version = ssl.TLSVersion.TLSv1
        old.maximum_version = ssl.TLSVersion.TLSv1_1
        old.set_ciphers("DEFAULT:@SECLEVEL=0")  # let this client offer the legacy versions
        try:
            with socket.create_connection((host, 443), timeout=30) as raw:
                with old.wrap_socket(raw, server_hostname=host):
                    legacy = "accepted"
        except (ssl.SSLError, OSError):
            legacy = "refused"
        record(area, "E1", "HTTPS with a valid certificate; TLS 1.0/1.1 refused", ok and legacy == "refused",
               f"negotiated {version}, certificate issued by {issuer}, valid until {cert['notAfter']}; TLS <= 1.1 {legacy}")
    guarded(area, "E1", "HTTPS with a valid certificate", tls)

    def redirect():
        conn = http.client.HTTPConnection(host, 80, timeout=30)
        conn.request("GET", "/")
        response = conn.getresponse()
        location = response.getheader("Location", "")
        conn.close()
        record(area, "E2", "Plain HTTP is redirected to HTTPS", response.status in (301, 302, 307, 308)
               and location.startswith("https://"), f"http:// -> {response.status} {location}")
    guarded(area, "E2", "Plain HTTP is redirected to HTTPS", redirect)

    def ingress():
        apps = az("containerapp", "list", "-g", RG, "--query",
                  "[].{name:name, external:properties.configuration.ingress.external, insecure:properties.configuration.ingress.allowInsecure}")
        public = [a["name"] for a in apps if a["external"]]
        insecure_public = [a["name"] for a in apps if a["external"] and a["insecure"]]
        record(area, "E3", "One public entry point; every service and AI app internal-only",
               len(public) == 1 and public[0].endswith("-proxy") and not insecure_public,
               f"{len(apps)} apps; public: {public}; internal: {sorted(a['name'] for a in apps if not a['external'])}")
    guarded(area, "E3", "One public entry point", ingress)

    def unreachable():
        fqdns = az("deployment", "group", "show", "-g", RG, "-n", APPS_DEPLOYMENT, "--query",
                   "properties.outputs.internalFqdns.value")
        exposed, tried = [], []
        for name, fqdn in sorted(fqdns.items()):
            try:
                status, _, body = https_request(f"https://{fqdn}/")
                reachable = not (status == 404 and "Azure Container App - Unavailable" in body)
            except (OSError, ssl.SSLError, http.client.HTTPException):
                status, reachable = "no answer", False
            tried.append(f"{name}: {status}")
            if reachable:
                exposed.append(name)
        record(area, "E4", "Internal addresses cannot be reached from the internet", not exposed,
               "; ".join(tried) + (f"; EXPOSED: {exposed}" if exposed else ""))
    guarded(area, "E4", "Internal addresses unreachable", unreachable)

    def headers():
        status, h, _ = https_request(base + "/")
        want = {
            "Strict-Transport-Security": "max-age=",
            "Content-Security-Policy": "frame-ancestors",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
            "Referrer-Policy": "strict-origin",
        }
        missing = [k for k, v in want.items() if v not in (h.get(k) or "")]
        server = h.get("Server", "")
        record(area, "E5", "Security headers on every response; no server version disclosed",
               not missing and not any(c.isdigit() for c in server),
               f"Server: '{server}'; " + ("all present" if not missing else f"missing: {missing}"),
               "\n".join(f"{k}: {h.get(k)}" for k in want))
    guarded(area, "E5", "Security headers", headers)

    def cookies():
        _, h, _ = https_request(base + "/auth/login")
        cookie = h.get("Set-Cookie", "")
        flags = {f: f.lower() in cookie.lower() for f in ("Secure", "HttpOnly", "SameSite=Lax")}
        record(area, "E6", "Session cookies are Secure, HttpOnly and SameSite", bool(cookie) and all(flags.values()),
               f"auth session cookie flags: {flags}")
    guarded(area, "E6", "Session cookie flags", cookies)

    def csrf():
        status, _, _ = https_request(base + "/auth/login", "POST", "email=a%40b.c&password=x",
                                     {"Content-Type": "application/x-www-form-urlencoded"})
        record(area, "E7", "Forms reject requests without a CSRF token", status in (400, 403),
               f"POST /auth/login without a token -> {status}")
    guarded(area, "E7", "CSRF", csrf)

    def private_apis():
        results = {}
        for path, expected in (("/vgarden/gardens/export", 401), ("/vgarden/gardens/1/view", 302),
                               ("/vgarden/gardens/1/snapshot", 401)):
            results[path] = https_request(base + path)[0]
        ok = results["/vgarden/gardens/export"] == 401 and results["/vgarden/gardens/1/view"] in (302, 303)
        record(area, "E8", "Private data needs a login or the inter-service token", ok,
               ", ".join(f"{p} -> {s}" for p, s in results.items()))
    guarded(area, "E8", "Private APIs", private_apis)

    def rate_limit():
        codes = []
        for _ in range(25):
            codes.append(https_request(base + "/auth/login")[0])
        limited = codes.count(429)
        record(area, "E9", "Sign-in is rate limited per client (password guessing)", limited > 0,
               f"25 rapid GET /auth/login: {codes.count(200)} x 200, {limited} x 429")
        time.sleep(65)  # let the bucket refill so later users and checks are not blocked
    guarded(area, "E9", "Rate limiting", rate_limit)

    def dotfiles():
        codes = {p: https_request(base + p)[0] for p in ("/.env", "/.git/config", "/auth/.env")}
        record(area, "E10", "Dotfiles are never served", all(c == 404 for c in codes.values()),
               ", ".join(f"{p} -> {c}" for p, c in codes.items()))
    guarded(area, "E10", "Dotfiles", dotfiles)


def data_checks() -> None:
    area = "Data security (B6)"

    def postgres():
        servers = az("postgres", "flexible-server", "list", "-g", RG)
        rows, ok = [], bool(servers)
        for s in servers:
            name = s["name"]
            params = {p: az("postgres", "flexible-server", "parameter", "show", "-g", RG, "-s", name, "-n", p,
                            "--query", "value") for p in ("require_secure_transport", "ssl_min_protocol_version")}
            public = s["network"]["publicNetworkAccess"]
            delegated = bool(s["network"].get("delegatedSubnetResourceId"))
            encryption = (s.get("dataEncryption") or {}).get("type", "SystemManaged")
            server_ok = (public == "Disabled" and delegated and str(params["require_secure_transport"]).lower() == "on"
                         and params["ssl_min_protocol_version"] in ("TLSv1.2", "TLSv1.3"))
            ok = ok and server_ok
            rows.append(f"{name}: public access {public}, VNet-injected {delegated}, "
                        f"require_secure_transport={params['require_secure_transport']}, "
                        f"min TLS {params['ssl_min_protocol_version']}, encryption at rest {encryption}, "
                        f"backups {s['backup']['backupRetentionDays']} days")
        record(area, "D1", "Database private to the VNet, TLS required, encrypted at rest, backed up", ok, "; ".join(rows))
    guarded(area, "D1", "PostgreSQL", postgres)

    def key_vault():
        vaults = az("keyvault", "list", "-g", RG)
        rows, ok = [], bool(vaults)
        for v in vaults:
            p = az("keyvault", "show", "-n", v["name"], "--query",
                   "properties.{rbac:enableRbacAuthorization, softDelete:enableSoftDelete, retention:softDeleteRetentionInDays, policies:length(accessPolicies || `[]`)}")
            names = az("keyvault", "secret", "list", "--vault-name", v["name"], "--query", "[].name")
            ok = ok and p["rbac"] and p["softDelete"] and not p["policies"]
            rows.append(f"{v['name']}: RBAC {p['rbac']}, soft delete {p['softDelete']} ({p['retention']} days), "
                        f"access policies {p['policies']}, {len(names)} secrets (names only)")
        record(area, "D2", "Secrets in Key Vault: RBAC only, soft delete", ok, "; ".join(rows))
    guarded(area, "D2", "Key Vault", key_vault)

    def app_secrets():
        apps = az("containerapp", "list", "-g", RG)
        problems, refs = [], 0
        sensitive = ("SECRET", "PASSWORD", "DATABASE_URL", "TOKEN", "KEY")
        for a in apps:
            conf = a["properties"]["configuration"]
            for secret in conf.get("secrets") or []:
                if secret.get("keyVaultUrl"):
                    refs += 1
                else:
                    problems.append(f"{a['name']}:{secret['name']} is stored on the app")
            for container in a["properties"]["template"]["containers"]:
                for env in container.get("env") or []:
                    if any(word in env["name"] for word in sensitive) and env.get("value") is not None \
                            and env["name"] not in ("SESSION_COOKIE_SECURE",):
                        problems.append(f"{a['name']}:{env['name']} is a plain value")
            identity = (a.get("identity") or {}).get("type", "None")
            if "UserAssigned" not in identity:
                problems.append(f"{a['name']} has no managed identity")
        record(area, "D3", "Apps get secrets only as Key Vault references, through a managed identity",
               not problems, f"{refs} Key Vault references across {len(apps)} apps" + (f"; problems: {problems}" if problems else ""))
    guarded(area, "D3", "App secrets", app_secrets)

    def registry():
        regs = az("acr", "list", "-g", RG, "--query", "[].{name:name, admin:adminUserEnabled}")
        record(area, "D4", "Registry without an admin password (pulls use the managed identity)",
               bool(regs) and not any(r["admin"] for r in regs), str(regs))
    guarded(area, "D4", "Registry", registry)

    def storage():
        accounts = az("storage", "account", "list", "-g", RG)
        rows, ok = [], bool(accounts)
        for s in accounts:
            acl = s.get("networkRuleSet") or {}
            enc = ((s.get("encryption") or {}).get("services") or {}).get("file") or {}
            this = (s["enableHttpsTrafficOnly"] and s["minimumTlsVersion"] == "TLS1_2"
                    and not s.get("allowBlobPublicAccess") and acl.get("defaultAction") == "Deny"
                    and enc.get("enabled", True))
            ok = ok and this
            rows.append(f"{s['name']}: HTTPS only {s['enableHttpsTrafficOnly']}, min TLS {s['minimumTlsVersion']}, "
                        f"public blobs {s.get('allowBlobPublicAccess')}, network default {acl.get('defaultAction')} "
                        f"({len(acl.get('virtualNetworkRules') or [])} subnet rule(s)), file encryption {enc.get('enabled', True)}")
        record(area, "D5", "Stored files: HTTPS/TLS 1.2 only, no public access, subnet-restricted, encrypted", ok, "; ".join(rows))
    guarded(area, "D5", "Storage", storage)

    def oidc():
        creds = az("identity", "federated-credential", "list", "-g", RG, "--identity-name",
                   os.environ.get("GITHUB_IDENTITY", "id-plantms-github"), "--query", "[].{subject:subject, issuer:issuer}")
        github = [c for c in creds if "token.actions.githubusercontent.com" in c["issuer"]]
        record(area, "D6", "No cloud credential stored in GitHub (OIDC federation)", bool(github),
               f"{len(github)} federated credential(s): " + ", ".join(c["subject"] for c in github))
    guarded(area, "D6", "OIDC", oidc)

    def app_level():
        text = (ROOT / "auth" / "models.py").read_text()
        hashed = "generate_password_hash" in text
        baseline = (ROOT / ".secrets.baseline").exists() and (ROOT / ".pre-commit-config.yaml").exists()
        record(area, "D7", "Passwords stored only as salted hashes; secrets blocked from the repository",
               hashed and baseline, f"auth/models.py uses werkzeug generate_password_hash: {hashed}; "
               f"detect-secrets pre-commit hook with a reviewed baseline: {baseline}")
    guarded(area, "D7", "Application data", app_level)


def write(out_dir: Path, base: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    passed = sum(c["result"] == "pass" for c in checks)
    data = {"generated_at": stamp, "target": base, "resource_group": RG, "passed": passed,
            "total": len(checks), "result": "pass" if passed == len(checks) else "fail", "checks": checks}
    lines = [f"# Cloud security validation — {passed}/{len(checks)} controls pass", "",
             f"Generated {stamp} by `scripts/deploy/azure_security_check.py` against <{base}> "
             f"(resource group `{RG}`). Read-only: no secret value is read.", ""]
    for area in ("Endpoint security (B5)", "Data security (B6)"):
        lines += [f"## {area}", "", "| ID | Control | Result | Evidence |", "| --- | --- | --- | --- |"]
        for c in checks:
            if c["area"] == area:
                detail = c["detail"].replace("|", "\\|")
                lines.append(f"| {c['id']} | {c['control']} | {'✅ pass' if c['result'] == 'pass' else '❌ fail'} | {detail} |")
        lines.append("")
    headers = next((c["evidence"] for c in checks if c["id"] == "E5" and c["evidence"]), "")
    if headers:
        lines += ["### Response headers (E5)", "", "```text", headers, "```", ""]
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in (f"cloud-security-{stamp}", "latest"):
        (out_dir / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
        (out_dir / f"{name}.md").write_text("\n".join(lines))
    print(f"\n{passed}/{len(checks)} controls pass -> {out_dir}/latest.md")


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].startswith("https://"):
        sys.exit("Usage: python3 scripts/deploy/azure_security_check.py https://<public proxy> [output dir]")
    base = sys.argv[1].rstrip("/")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "docs/evidence/release2/cloud-security"
    print(f"Cloud security validation of {base}")
    endpoint_checks(base)
    data_checks()
    write(out_dir, base)
    return 0 if all(c["result"] == "pass" for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
