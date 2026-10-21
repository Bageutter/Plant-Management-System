# Cloud deployment evidence

Reports written by `scripts/deploy/azure-report.sh` at the end of every deployment
(`cloud-deployment.yml` uploads the same files as a workflow artifact):

- `cloud-deployment-<timestamp>.md` — the deployment report for the technical
  report: commit, workflow run, public URLs, cloud baseline switches, container
  apps and revisions, database, security controls, and the final human release
  decision checklist.
- `cloud-deployment-<timestamp>.json` — the same facts as JSON grounding for the
  shared agentic loop's Cloud Deployment Review mode.
- `latest.md` / `latest.json` — copies of the newest run.

Commit the files from the run you cite in the report, together with the agentic
loop's review/validation log for it. See
[docs/deployment/azure.md](../../../deployment/azure.md) §5.
