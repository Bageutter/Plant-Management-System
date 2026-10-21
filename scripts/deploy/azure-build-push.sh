#!/usr/bin/env bash
# Build the six images and push them to the registry the platform created.
#
# The service Dockerfiles copy only their own directory, and docker compose mounts
# the two shared pieces at run time (./shared/templates -> /app/shared_templates,
# ./shared/ai_loop.py -> /app/ai_loop.py). Nothing is mounted in the cloud, so the
# build context is assembled here as <service dir> + those two files, at exactly
# the paths compose would mount them. The Dockerfiles stay untouched.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"
require_az_login

acr_name=$(platform_output acrName)
acr_server=$(platform_output acrLoginServer)

step "Signing in to $acr_server"
az acr login --name "$acr_name" -o none

stage_dir=$(mktemp -d)
trap 'rm -rf "$stage_dir"' EXIT

assemble() { # <service source dir relative to ROOT> -> prints the staged context
  local dst="$stage_dir/$(basename "$1")"
  cp -R "$ROOT/$1" "$dst"
  cp -R "$ROOT/shared/templates" "$dst/shared_templates"
  cp "$ROOT/shared/ai_loop.py" "$dst/ai_loop.py"
  echo "$dst"
}

context_for() {
  case $1 in
    proxy) echo "$ROOT/shared/proxy" ;;
    frontend) assemble shared/frontend ;;
    *) assemble "$1" ;;
  esac
}

for service in "${SERVICES[@]}"; do
  image="$acr_server/$AZURE_BASE_NAME/$service"
  context=$(context_for "$service")
  step "Building $image:$IMAGE_TAG"
  docker build --platform "$IMAGE_PLATFORM" \
    --tag "$image:$IMAGE_TAG" --tag "$image:latest" "$context"
  docker push --all-tags "$image"
done

step "Images in $acr_server"
az acr repository list --name "$acr_name" -o tsv | tr -d '\r' | sed 's/^/    /'
