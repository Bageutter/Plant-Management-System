# Shared settings and helpers for scripts/deploy/azure-*.sh. Source, don't run.
#
# Every value can be overridden with an environment variable; the GitHub Actions
# workflow passes them from repository variables, a developer exports them in the
# shell. Nothing here is secret.

# Git Bash on Windows rewrites arguments that look like POSIX paths
# (/subscriptions/... -> C:/Program Files/Git/subscriptions/...). Never do that.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

ROOT=${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}

AZURE_BASE_NAME=${AZURE_BASE_NAME:-plantms}
AZURE_STAGE=${AZURE_STAGE:-prod}
AZURE_LOCATION=${AZURE_LOCATION:-australiaeast}
AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-rg-${AZURE_BASE_NAME}-${AZURE_STAGE}}

# Managed identities created once by azure-bootstrap.sh.
APPS_IDENTITY=${APPS_IDENTITY:-id-${AZURE_BASE_NAME}-apps}
GITHUB_IDENTITY=${GITHUB_IDENTITY:-id-${AZURE_BASE_NAME}-github}

GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-Bageutter/Plant-Management-System}
GITHUB_ENVIRONMENT=${GITHUB_ENVIRONMENT:-azure-production}

PLATFORM_DEPLOYMENT=${PLATFORM_DEPLOYMENT:-${AZURE_BASE_NAME}-platform}
APPS_DEPLOYMENT=${APPS_DEPLOYMENT:-${AZURE_BASE_NAME}-apps}

# Images are tagged with the short commit SHA (what CI deploys) plus "latest".
IMAGE_TAG=${IMAGE_TAG:-$(git -C "$ROOT" rev-parse --short=7 HEAD 2>/dev/null || echo dev)}
IMAGE_PLATFORM=${IMAGE_PLATFORM:-linux/amd64}
SERVICES=(proxy frontend auth vgarden almanac health)

# Scaling for apps.bicep (see its parameters).
PROXY_MIN_REPLICAS=${PROXY_MIN_REPLICAS:-1}
SERVICE_MIN_REPLICAS=${SERVICE_MIN_REPLICAS:-0}

# Cloud baseline: all four AI services disabled. Only the bonus profile flips these.
CLOUD_AI_ENABLED=${CLOUD_AI_ENABLED:-false}
MCP_ENABLED=${MCP_ENABLED:-false}
RAG_ENABLED=${RAG_ENABLED:-false}
MULTI_AGENT_ENABLED=${MULTI_AGENT_ENABLED:-false}

# Where azure-report.sh writes the deployment report (committed as evidence).
REPORT_DIR=${REPORT_DIR:-$ROOT/docs/evidence/release2/cloud-deployment}

# --- helpers -------------------------------------------------------------------

# az with tsv output, without the carriage returns the Windows CLI adds.
azq() {
  az "$@" -o tsv | tr -d '\r'
}

platform_output() {
  azq deployment group show -g "$AZURE_RESOURCE_GROUP" -n "$PLATFORM_DEPLOYMENT" \
    --query "properties.outputs.$1.value"
}

apps_output() {
  azq deployment group show -g "$AZURE_RESOURCE_GROUP" -n "$APPS_DEPLOYMENT" \
    --query "properties.outputs.$1.value"
}

step() {
  printf '\n==> %s\n' "$*"
}

require_az_login() {
  if ! az account show -o none 2>/dev/null; then
    echo "Not signed in to Azure. Run: az login   (or azure/login in GitHub Actions)" >&2
    exit 1
  fi
}
