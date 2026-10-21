// The six container apps of the Plant Management System on the platform that
// main.bicep created. Deployed by scripts/deploy/azure-apps.sh after the images
// for `imageTag` have been pushed to the registry.
//
//   proxy    nginx, the only public endpoint (HTTPS, HTTP redirected). Same image
//            as docker compose; its upstreams point at the internal apps below.
//   frontend, auth, vgarden, almanac, health
//            the Flask services, internal ingress only, run under gunicorn, one
//            PostgreSQL database each, secrets from Key Vault.
//
// Cloud baseline (Assessment 3): AI-Mode, MCP, RAG and the Multi-Agent Server are
// DISABLED by default. The four *Enabled parameters exist for the optional bonus
// profile and default to false; with aiEnabled=false every model-backed feature is
// pointed at an unreachable local address, so it degrades the same way it does in
// CI (no model call is ever attempted off-box).

targetScope = 'resourceGroup'

@minLength(3)
@maxLength(10)
param baseName string = 'plantms'

@minLength(2)
@maxLength(8)
param stage string = 'prod'

param location string = resourceGroup().location

@description('Outputs of main.bicep (scripts/deploy/azure-apps.sh passes them through).')
param environmentName string
param acrLoginServer string
param keyVaultName string
param almanacStorageName string = 'almanac-instance'
param appsIdentityName string = 'id-${baseName}-apps'

@description('Image tag pushed by scripts/deploy/azure-build-push.sh (the short commit SHA).')
param imageTag string

@description('Images are <acrLoginServer>/<imageRepositoryPrefix>/<service>:<imageTag>.')
param imageRepositoryPrefix string = baseName

@description('Keep the public entry point warm; set 0 to scale everything to zero when idle.')
@minValue(0)
param proxyMinReplicas int = 1

@description('0 = services scale to zero when idle (cheapest; first request after idle takes ~20-40 s). Set 1 for demos.')
@minValue(0)
param serviceMinReplicas int = 0

@description('auth and vgarden are called server-to-server (auth -> vgarden for every garden action, almanac -> auth for every page), so a cold start there surfaces as "could not reach" errors. Keep them warm by default.')
@minValue(0)
param dependencyMinReplicas int = 1

// --- Optional bonus profile: all off for the required cloud baseline -------------
param aiEnabled bool = false
param ollamaUrl string = 'http://127.0.0.1:11434'
param mcpEnabled bool = false
param mcpServerUrl string = 'http://127.0.0.1:5105/mcp'
param ragEnabled bool = false
param ragServerUrl string = 'http://127.0.0.1:5106'
param multiAgentEnabled bool = false
param multiAgentUrl string = 'http://127.0.0.1:8003'

param tags object = {
  project: 'plant-management-system'
  stage: stage
  managedBy: 'bicep'
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource appsIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: appsIdentityName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

var domain = environment.properties.defaultDomain
var prefix = '${baseName}-${stage}'
var names = {
  proxy: '${prefix}-proxy'
  frontend: '${prefix}-frontend'
  auth: '${prefix}-auth'
  vgarden: '${prefix}-vgarden'
  almanac: '${prefix}-almanac'
  health: '${prefix}-health'
}

// Browser-facing addresses: everything goes through the proxy, path-routed exactly
// as on http://localhost:3000 locally.
var publicBaseUrl = 'https://${names.proxy}.${domain}'
var publicUrls = {
  auth: '${publicBaseUrl}/auth'
  vgarden: '${publicBaseUrl}/vgarden'
  health: '${publicBaseUrl}/health/plant-health-records/'
  almanac: '${publicBaseUrl}/almanac/'
}

// Service-to-service addresses: internal ingress, never reachable from the internet.
var internalFqdn = {
  frontend: '${names.frontend}.internal.${domain}'
  auth: '${names.auth}.internal.${domain}'
  vgarden: '${names.vgarden}.internal.${domain}'
  almanac: '${names.almanac}.internal.${domain}'
  health: '${names.health}.internal.${domain}'
}

var image = {
  proxy: '${acrLoginServer}/${imageRepositoryPrefix}/proxy:${imageTag}'
  frontend: '${acrLoginServer}/${imageRepositoryPrefix}/frontend:${imageTag}'
  auth: '${acrLoginServer}/${imageRepositoryPrefix}/auth:${imageTag}'
  vgarden: '${acrLoginServer}/${imageRepositoryPrefix}/vgarden:${imageTag}'
  almanac: '${acrLoginServer}/${imageRepositoryPrefix}/almanac:${imageTag}'
  health: '${acrLoginServer}/${imageRepositoryPrefix}/health:${imageTag}'
}

// The images' CMD is Flask's development server (fine behind compose with live
// reload). In the cloud the same image runs under gunicorn: no debugger, no
// reloader, several workers. --preload imports the app once so the start-up
// migration runs exactly once per replica.
var gunicorn = [
  'gunicorn'
  '--bind'
  '0.0.0.0:5000'
  '--workers'
  '2'
  '--threads'
  '4'
  '--timeout'
  '180'
  '--preload'
  '--access-logfile'
  '-'
  'app:app'
]

func secretUrl(vaultUri string, secretName string) string => '${vaultUri}secrets/${secretName}'

var vaultUri = keyVault.properties.vaultUri

// Shared by every Flask service.
var commonEnv = [
  { name: 'PYTHONUNBUFFERED', value: '1' }
  { name: 'AUTO_MIGRATE', value: 'true' }
  { name: 'SESSION_COOKIE_SECURE', value: 'true' }
  { name: 'AUTH_PUBLIC_URL', value: publicUrls.auth }
  { name: 'VGARDEN_PUBLIC_URL', value: publicUrls.vgarden }
  { name: 'HEALTH_PUBLIC_URL', value: publicUrls.health }
  { name: 'ALMANAC_PUBLIC_URL', value: publicUrls.almanac }
]

// Cloud baseline switches (all four services read the ones they know about).
var aiEnv = [
  { name: 'OLLAMA_URL', value: aiEnabled ? ollamaUrl : 'http://127.0.0.1:11434' }
  { name: 'OLLAMA_AUTO_PULL', value: string(aiEnabled) }
  { name: 'OLLAMA_PRELOAD', value: string(aiEnabled) }
  { name: 'MCP_ENABLED', value: string(mcpEnabled) }
  { name: 'MCP_SERVER_URL', value: mcpServerUrl }
  { name: 'RAG_ENABLED', value: string(ragEnabled) }
  { name: 'RAG_SERVER_URL', value: ragServerUrl }
  { name: 'MULTI_AGENT_ENABLED', value: string(multiAgentEnabled) }
  { name: 'MULTI_AGENT_URL', value: multiAgentUrl }
  { name: 'AI_LOOP_MAX_ITERATIONS', value: '2' }
  { name: 'AI_LOOP_LOG_DIR', value: '/tmp/ai-loop-logs' }
]

// ---------------------------------------------------------------------------
// proxy: the public entry point
// ---------------------------------------------------------------------------
module proxy 'modules/container-app.bicep' = {
  name: 'app-proxy'
  params: {
    name: names.proxy
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: image.proxy
    external: true
    targetPort: 80
    probePath: '/proxy-healthz'
    cpu: '0.25'
    memory: '0.5Gi'
    minReplicas: proxyMinReplicas
    maxReplicas: 2
    env: [
      { name: 'FRONTEND_UPSTREAM', value: '${internalFqdn.frontend}:80' }
      { name: 'FRONTEND_HOST', value: internalFqdn.frontend }
      { name: 'AUTH_UPSTREAM', value: '${internalFqdn.auth}:80' }
      { name: 'AUTH_HOST', value: internalFqdn.auth }
      { name: 'VGARDEN_UPSTREAM', value: '${internalFqdn.vgarden}:80' }
      { name: 'VGARDEN_HOST', value: internalFqdn.vgarden }
      { name: 'HEALTH_UPSTREAM', value: '${internalFqdn.health}:80' }
      { name: 'HEALTH_HOST', value: internalFqdn.health }
      { name: 'ALMANAC_UPSTREAM', value: '${internalFqdn.almanac}:80' }
      { name: 'ALMANAC_HOST', value: internalFqdn.almanac }
    ]
  }
}

// ---------------------------------------------------------------------------
// frontend: landing page linking to the features
// ---------------------------------------------------------------------------
module frontend 'modules/container-app.bicep' = {
  name: 'app-frontend'
  params: {
    name: names.frontend
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: image.frontend
    command: gunicorn
    cpu: '0.25'
    memory: '0.5Gi'
    minReplicas: serviceMinReplicas
    env: [
      { name: 'PYTHONUNBUFFERED', value: '1' }
      { name: 'AUTH_URL', value: publicUrls.auth }
      { name: 'HEALTH_URL', value: publicUrls.health }
      { name: 'ALMANAC_URL', value: publicUrls.almanac }
    ]
  }
}

// ---------------------------------------------------------------------------
// auth: accounts, sessions, "My Gardens" (talks to vgarden server-to-server)
// ---------------------------------------------------------------------------
module auth 'modules/container-app.bicep' = {
  name: 'app-auth'
  params: {
    name: names.auth
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: image.auth
    command: gunicorn
    probePath: '/login'
    minReplicas: max(serviceMinReplicas, dependencyMinReplicas)
    secrets: [
      { name: 'secret-key', keyVaultUrl: secretUrl(vaultUri, 'auth-secret-key') }
      { name: 'database-url', keyVaultUrl: secretUrl(vaultUri, 'database-url-auth') }
      { name: 'inter-service-secret', keyVaultUrl: secretUrl(vaultUri, 'inter-service-secret') }
    ]
    env: concat(commonEnv, [
      { name: 'SECRET_KEY', secretRef: 'secret-key' } // pragma: allowlist secret
      { name: 'DATABASE_URL', secretRef: 'database-url' } // pragma: allowlist secret
      { name: 'INTER_SERVICE_SECRET', secretRef: 'inter-service-secret' } // pragma: allowlist secret
      { name: 'VGARDEN_URL', value: 'http://${internalFqdn.vgarden}' }
    ])
  }
}

// ---------------------------------------------------------------------------
// vgarden: the Virtual Garden (source of truth for garden state)
// ---------------------------------------------------------------------------
module vgarden 'modules/container-app.bicep' = {
  name: 'app-vgarden'
  params: {
    name: names.vgarden
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: image.vgarden
    command: gunicorn
    probePath: '/healthz'
    minReplicas: max(serviceMinReplicas, dependencyMinReplicas)
    secrets: [
      { name: 'secret-key', keyVaultUrl: secretUrl(vaultUri, 'vgarden-secret-key') }
      { name: 'database-url', keyVaultUrl: secretUrl(vaultUri, 'database-url-vgarden') }
      { name: 'inter-service-secret', keyVaultUrl: secretUrl(vaultUri, 'inter-service-secret') }
    ]
    env: concat(commonEnv, aiEnv, [
      { name: 'SECRET_KEY', secretRef: 'secret-key' } // pragma: allowlist secret
      { name: 'DATABASE_URL', secretRef: 'database-url' } // pragma: allowlist secret
      { name: 'INTER_SERVICE_SECRET', secretRef: 'inter-service-secret' } // pragma: allowlist secret
    ])
  }
}

// ---------------------------------------------------------------------------
// almanac: public plant catalogue (asks auth who is logged in; stores images)
// ---------------------------------------------------------------------------
module almanac 'modules/container-app.bicep' = {
  name: 'app-almanac'
  params: {
    name: names.almanac
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: image.almanac
    command: gunicorn
    probePath: '/'
    minReplicas: serviceMinReplicas
    secrets: [
      { name: 'secret-key', keyVaultUrl: secretUrl(vaultUri, 'almanac-secret-key') }
      { name: 'database-url', keyVaultUrl: secretUrl(vaultUri, 'database-url-almanac') }
    ]
    env: concat(commonEnv, aiEnv, [
      { name: 'SECRET_KEY', secretRef: 'secret-key' } // pragma: allowlist secret
      { name: 'DATABASE_URL', secretRef: 'database-url' } // pragma: allowlist secret
      { name: 'AUTH_URL', value: 'http://${internalFqdn.auth}' }
      // Copy the public My Garden catalogue into the empty cloud database on first start.
      { name: 'LOAD_MY_GARDEN_SEED', value: 'true' }
      // Uploaded plant images persist on the Azure Files share mounted below.
      { name: 'PLANT_IMAGE_FOLDER', value: '/app/instance/plant_images' }
    ])
    volumes: [
      { name: 'instance', storageType: 'AzureFile', storageName: almanacStorageName }
    ]
    volumeMounts: [
      { volumeName: 'instance', mountPath: '/app/instance' }
    ]
  }
}

// ---------------------------------------------------------------------------
// health: plant health records (photos are stored in its database)
// ---------------------------------------------------------------------------
module health 'modules/container-app.bicep' = {
  name: 'app-health'
  params: {
    name: names.health
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: image.health
    command: gunicorn
    // Not /healthz: that reports 503 while the (disabled) model is unreachable.
    probePath: '/'
    minReplicas: serviceMinReplicas
    secrets: [
      { name: 'database-url', keyVaultUrl: secretUrl(vaultUri, 'database-url-health') }
    ]
    env: concat(commonEnv, aiEnv, [
      { name: 'DATABASE_URL', secretRef: 'database-url' } // pragma: allowlist secret
    ])
  }
}

output appUrl string = publicBaseUrl
output proxyFqdn string = proxy.outputs.fqdn
output publicUrls object = publicUrls
output internalFqdns object = internalFqdn
output imageTag string = imageTag
output cloudBaseline object = {
  aiMode: aiEnabled
  mcp: mcpEnabled
  rag: ragEnabled
  multiAgent: multiAgentEnabled
}
