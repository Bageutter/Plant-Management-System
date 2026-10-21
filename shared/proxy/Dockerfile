FROM nginx:1.27-alpine

# The routing table is a template. The image's own entrypoint renders it to
# /etc/nginx/conf.d/default.conf with envsubst before nginx starts, so the same
# image serves docker compose locally and Azure Container Apps in the cloud.
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY 15-proxy-resolver.envsh /docker-entrypoint.d/15-proxy-resolver.envsh

# Substitute only our variables, never nginx's own ($host, $scheme, ...).
ENV NGINX_ENVSUBST_FILTER="^((FRONTEND|AUTH|VGARDEN|HEALTH|ALMANAC)_(UPSTREAM|HOST)|PROXY_DNS_RESOLVER)$"

# Defaults = the docker compose service names, with the client's own Host header
# passed through. Azure overrides every one of these with the service's internal
# Container Apps FQDN (see infra/apps.bicep), because that ingress routes by Host.
ENV FRONTEND_UPSTREAM=frontend:5000 FRONTEND_HOST=\$host \
    AUTH_UPSTREAM=auth:5000         AUTH_HOST=\$host \
    VGARDEN_UPSTREAM=vgarden:5000   VGARDEN_HOST=\$host \
    HEALTH_UPSTREAM=health:5000     HEALTH_HOST=\$host \
    ALMANAC_UPSTREAM=almanac:5000   ALMANAC_HOST=\$host

EXPOSE 80
