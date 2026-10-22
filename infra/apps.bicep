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
@description('Bonus profile: run Ollama, MCP, RAG and the Multi-Agent Server as internal container apps in this environment. Their URLs then replace the four *Url parameters below.')
param aiServicesDeployed bool = false
param ollamaStorageName string = 'ollama-models'
@description('Ollama image imported into the registry by scripts/deploy/azure-build-push.sh.')
param ollamaImage string = ''
@description('Text model for chats, agents, RAG and reviews; vision model for Plant Health.')
param textModel string = 'qwen3:4b-instruct'
param visionModel string = 'qwen2.5vl:3b'
@description('0 = the AI apps scale to zero when idle (Ollama is 4 vCPU / 8 GiB while running).')
@minValue(0)
param aiMinReplicas int = 0
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
  ollama: '${prefix}-ollama'
  mcp: '${prefix}-mcp'
  rag: '${prefix}-rag'
  agents: '${prefix}-agents'
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

// Bonus profile: the AI services' internal addresses (never reachable from the internet).
var aiFqdn = {
  ollama: '${names.ollama}.internal.${domain}'
  mcp: '${names.mcp}.internal.${domain}'
  rag: '${names.rag}.internal.${domain}'
  agents: '${names.agents}.internal.${domain}'
}
var ollamaEndpoint = aiServicesDeployed ? 'http://${aiFqdn.ollama}' : ollamaUrl
var mcpEndpoint = aiServicesDeployed ? 'http://${aiFqdn.mcp}/mcp' : mcpServerUrl
var ragEndpoint = aiServicesDeployed ? 'http://${aiFqdn.rag}' : ragServerUrl
var agentsEndpoint = aiServicesDeployed ? 'http://${aiFqdn.agents}' : multiAgentUrl
// The cloud ingress ends a request after 240 s, so every model call stays under it.
var modelTimeout = aiServicesDeployed ? '230' : '120'

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
  // Explicit AI-Mode switch (health saves records "not assessed" when off).
  { name: 'AI_MODE_ENABLED', value: string(aiEnabled) }
  { name: 'OLLAMA_URL', value: aiEnabled ? ollamaEndpoint : 'http://127.0.0.1:11434' }
  { name: 'OLLAMA_AUTO_PULL', value: string(aiEnabled) }
  { name: 'OLLAMA_PRELOAD', value: string(aiEnabled) }
  { name: 'OLLAMA_TIMEOUT', value: modelTimeout }
  { name: 'MCP_ENABLED', value: string(mcpEnabled) }
  { name: 'MCP_SERVER_URL', value: mcpEndpoint }
  { name: 'RAG_ENABLED', value: string(ragEnabled) }
  { name: 'RAG_SERVER_URL', value: ragEndpoint }
  { name: 'MULTI_AGENT_ENABLED', value: string(multiAgentEnabled) }
  { name: 'MULTI_AGENT_URL', value: agentsEndpoint }
  // The Almanac reads its own name for the same setting.
  { name: 'MULTI_AGENT_SERVER_URL', value: agentsEndpoint }
  { name: 'AI_LOOP_MAX_ITERATIONS', value: '2' }
  { name: 'AI_LOOP_LOG_DIR', value: '/tmp/ai-loop-logs' }
]

// One text model in the cloud: the local review default (llama3.1:8b) does not fit
// next to the others in Ollama's 8 GiB.
var textModelEnv = [
  { name: 'OLLAMA_MODEL', value: textModel }
  { name: 'OLLAMA_REVIEW_MODEL', value: textModel }
]
var visionModelEnv = [
  { name: 'OLLAMA_MODEL', value: visionModel }
  { name: 'OLLAMA_REVIEW_MODEL', value: textModel }
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
    env: concat(commonEnv, aiEnv, textModelEnv, [
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
    env: concat(commonEnv, aiEnv, textModelEnv, [
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
    env: concat(commonEnv, aiEnv, visionModelEnv, [
      { name: 'DATABASE_URL', secretRef: 'database-url' } // pragma: allowlist secret
    ])
  }
}

// ===========================================================================
// Bonus profile (B1-B4): the shared AI services, as internal-only container apps.
// The required cloud baseline deploys none of these (aiServicesDeployed=false).
// ===========================================================================

// Ollama (AI-Mode): CPU inference, models kept on an Azure Files share so a
// restart or scale-from-zero does not download them again.
module ollama 'modules/container-app.bicep' = if (aiServicesDeployed) {
  name: 'app-ollama'
  params: {
    name: names.ollama
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: ollamaImage
    targetPort: 11434
    // Serve at once, then fetch any missing model in the background (a no-op once
    // the share holds them).
    command: [
      '/bin/sh'
      '-c'
      'ollama serve & pid=$!; sleep 5; for m in $OLLAMA_PULL_MODELS; do ollama pull "$m" || echo "pull $m failed"; done; wait $pid'
    ]
    cpu: '4'
    memory: '8Gi'
    probePath: '/'
    minReplicas: aiMinReplicas
    maxReplicas: 1
    env: [
      { name: 'OLLAMA_HOST', value: '0.0.0.0:11434' }
      { name: 'OLLAMA_PULL_MODELS', value: '${textModel} ${visionModel}' }
      // One model in memory at a time; requests queue instead of overcommitting 8 GiB.
      { name: 'OLLAMA_MAX_LOADED_MODELS', value: '1' }
      { name: 'OLLAMA_NUM_PARALLEL', value: '1' }
      { name: 'OLLAMA_KEEP_ALIVE', value: '15m' }
    ]
    volumes: [
      { name: 'models', storageType: 'AzureFile', storageName: ollamaStorageName }
    ]
    volumeMounts: [
      { volumeName: 'models', mountPath: '/root/.ollama' }
    ]
  }
}

// Feature addresses the AI services call: internal ingress, no proxy prefix.
var featureServiceUrls = [
  { name: 'HEALTH_SERVICE_URL', value: 'http://${internalFqdn.health}' }
  { name: 'ALMANAC_SERVICE_URL', value: 'http://${internalFqdn.almanac}' }
  { name: 'VGARDEN_SERVICE_URL', value: 'http://${internalFqdn.vgarden}' }
  // Cold features take 20-40 s to answer their first request.
  { name: 'SERVICE_TIMEOUT', value: '60' }
]

// MCP server: tools over the features' APIs (vgarden's with the inter-service token).
module mcp 'modules/container-app.bicep' = if (aiServicesDeployed) {
  name: 'app-mcp'
  params: {
    name: names.mcp
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: '${acrLoginServer}/${imageRepositoryPrefix}/mcp-server:${imageTag}'
    targetPort: 5105
    probePath: '/healthz'
    minReplicas: aiMinReplicas
    secrets: [
      { name: 'inter-service-secret', keyVaultUrl: secretUrl(vaultUri, 'inter-service-secret') }
    ]
    env: concat(featureServiceUrls, [
      { name: 'MCP_ENABLED', value: string(mcpEnabled) }
      // DNS-rebinding protection: only its own internal name (and the probe's loopback).
      { name: 'MCP_ALLOWED_HOSTS', value: '${aiFqdn.mcp},${aiFqdn.mcp}:*,127.0.0.1:*,localhost:*' }
      { name: 'RAG_SERVICE_URL', value: ragEndpoint }
      { name: 'ASSESS_TIMEOUT', value: modelTimeout }
      { name: 'VGARDEN_SERVICE_TOKEN', secretRef: 'inter-service-secret' } // pragma: allowlist secret
    ])
  }
}

// RAG server: index rebuilt from the features at start and every 10 minutes.
module rag 'modules/container-app.bicep' = if (aiServicesDeployed) {
  name: 'app-rag'
  params: {
    name: names.rag
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: '${acrLoginServer}/${imageRepositoryPrefix}/rag-server:${imageTag}'
    targetPort: 5106
    // Not /healthz: that answers 503 while Ollama is still scaling up from zero.
    probePath: '/'
    minReplicas: aiMinReplicas
    secrets: [
      { name: 'inter-service-secret', keyVaultUrl: secretUrl(vaultUri, 'inter-service-secret') }
    ]
    env: concat(featureServiceUrls, [
      { name: 'RAG_ENABLED', value: string(ragEnabled) }
      { name: 'OLLAMA_URL', value: ollamaEndpoint }
      { name: 'OLLAMA_MODEL', value: textModel }
      { name: 'OLLAMA_AUTO_PULL', value: 'false' }
      { name: 'OLLAMA_TIMEOUT', value: modelTimeout }
      // Citations link to the public pages.
      { name: 'HEALTH_PUBLIC_URL', value: '${publicBaseUrl}/health' }
      { name: 'ALMANAC_PUBLIC_URL', value: '${publicBaseUrl}/almanac' }
      { name: 'VGARDEN_PUBLIC_URL', value: '${publicBaseUrl}/vgarden' }
      { name: 'VGARDEN_SERVICE_TOKEN', secretRef: 'inter-service-secret' } // pragma: allowlist secret
    ])
  }
}

// Multi-Agent Server: Planner -> Worker -> Reviewer, human review in the features.
module agents 'modules/container-app.bicep' = if (aiServicesDeployed) {
  name: 'app-agents'
  params: {
    name: names.agents
    location: location
    tags: tags
    environmentId: environment.id
    identityId: appsIdentity.id
    acrLoginServer: acrLoginServer
    image: '${acrLoginServer}/${imageRepositoryPrefix}/multi-agent-server:${imageTag}'
    targetPort: 8003
    probePath: '/healthz'
    minReplicas: aiMinReplicas
    env: [
      { name: 'OLLAMA_URL', value: ollamaEndpoint }
      { name: 'OLLAMA_MODEL', value: textModel }
      { name: 'REVIEWER_MODEL', value: textModel }
      { name: 'OLLAMA_TIMEOUT', value: modelTimeout }
      { name: 'MCP_SERVER_URL', value: mcpEndpoint }
    ]
  }
}

output appUrl string = publicBaseUrl
output proxyFqdn string = proxy.outputs.fqdn
output publicUrls object = publicUrls
output internalFqdns object = aiServicesDeployed ? union(internalFqdn, aiFqdn) : internalFqdn
output imageTag string = imageTag
output cloudBaseline object = {
  aiMode: aiEnabled
  mcp: mcpEnabled
  rag: ragEnabled
  multiAgent: multiAgentEnabled
  aiServicesDeployed: aiServicesDeployed
  textModel: aiServicesDeployed ? textModel : ''
  visionModel: aiServicesDeployed ? visionModel : ''
}
