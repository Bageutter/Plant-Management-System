# Cloud security evidence (endpoint + data security bonus)

`scripts/deploy/azure_security_check.py` is a read-only check: `az` queries plus HTTPS
probes, and no secret value is ever read. The deploy job runs it after every cloud
deployment (`.github/workflows/cloud-deployment.yml`, step "Cloud security validation").

| File | What |
| --- | --- |
| `latest.md` / `latest.json` | **17/17 controls pass**. Run on the bonus deployment (workflow run [39745279626](https://github.com/Bageutter/Plant-Management-System/actions/runs/39745279626), commit `7dbd213`), so it also covers the four AI apps. |
| `cloud-security-20261022T082443Z.*` | the same run, timestamped |

- **Endpoint security (E1–E10):**
  - TLS 1.2+ with plain HTTP redirected.
  - The proxy is the only public app, and every internal address returns 404 from the internet.
  - Security headers (HSTS, CSP, frame, nosniff, referrer, permissions), with no server version shown.
  - Secure, HttpOnly, SameSite cookies.
  - CSRF on forms.
  - Login or the inter-service token required for private data.
  - Per-client sign-in rate limit.
  - No dotfiles served.
- **Data security (D1–D7):**
  - PostgreSQL is VNet-only, requires TLS, and is encrypted and backed up.
  - Key Vault uses RBAC with soft delete.
  - Secrets reach apps only as Key Vault references through a managed identity.
  - The registry has no admin password.
  - Storage is HTTPS-only, private and subnet-restricted.
  - GitHub OIDC is used, so no cloud credential is stored.
  - Passwords are salted hashes, and detect-secrets runs on every commit.

Run it yourself:

    python3 scripts/deploy/azure_security_check.py https://plantms-prod-proxy.<env>.azurecontainerapps.io
