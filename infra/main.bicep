// Azure platform for the Plant Management System (Release 2 cloud baseline).
//
// One resource group holds everything. Deployed by scripts/deploy/azure-platform.sh,
// locally or from .github/workflows/cloud-deployment.yml. The container apps
// themselves live in apps.bicep, a second deployment, because they need images
// that are pushed to the registry created here.
//
//   VNet ─┬─ snet-apps      Container Apps environment. Only the proxy has public
//         │                 (HTTPS-only) ingress; every service is internal.
//         └─ snet-postgres  PostgreSQL Flexible Server, private access only, one
//                           database per service (auth, vgarden, health, almanac).
//   Key Vault (RBAC)        holds every secret; apps read them with a managed identity.
//   Container Registry      managed-identity pull, admin user disabled.
//   Storage + file share    the Almanac's uploaded plant images (its /app/instance).
//   Log Analytics           container logs.
//
// Cloud baseline rule: AI-Mode, MCP, RAG and the Multi-Agent Server are switched
// off by apps.bicep; nothing here runs a model.

targetScope = 'resourceGroup'

@description('Short name shared by every resource (lowercase letters and digits).')
@minLength(3)
@maxLength(10)
param baseName string = 'plantms'

@description('Deployment stage, e.g. prod.')
@minLength(2)
@maxLength(8)
param stage string = 'prod'

param location string = resourceGroup().location

@description('User-assigned identity the container apps run as (created once by scripts/deploy/azure-bootstrap.sh, which also grants it AcrPull and Key Vault Secrets User).')
param appsIdentityName string = 'id-${baseName}-apps'

param postgresAdminLogin string = 'plantadmin'

@secure()
param postgresAdminPassword string

@secure()
param authSecretKey string

@secure()
param vgardenSecretKey string

@secure()
param almanacSecretKey string

@description('Shared bearer token for auth -> vgarden server-to-server calls.')
@secure()
param interServiceSecret string

param postgresSkuName string = 'Standard_B1ms'
param postgresStorageGb int = 32
param postgresVersion string = '16'

// Create the PostgreSQL server. azure-platform.sh passes false once it exists: re-sending the
// full definition of an existing VNet-injected server leaves the deployment stuck in Running (seen
// twice), so later runs only reference it. Its databases, DNS, network and secrets still deploy every time.
@description('Create the PostgreSQL server (false: reference the existing one)')
param deployPostgres bool = true

@description('Restrict the plant-image storage account to the apps subnet (Microsoft.Storage service endpoint). Set false only if the Almanac volume fails to mount.')
param storageRestrictToVnet bool = true

param tags object = {
  project: 'plant-management-system'
  stage: stage
  managedBy: 'bicep'
}

var suffix = uniqueString(resourceGroup().id)
var databaseNames = ['auth', 'vgarden', 'health', 'almanac']

var logName = 'log-${baseName}-${stage}'
var vnetName = 'vnet-${baseName}-${stage}'
var appsSubnetName = 'snet-apps'
var postgresSubnetName = 'snet-postgres'
var postgresName = 'psql-${baseName}-${stage}-${suffix}'
var postgresDnsZoneName = '${baseName}-${stage}.private.postgres.database.azure.com'
var keyVaultName = 'kv-${baseName}-${take(suffix, 8)}'
var acrName = 'acr${baseName}${suffix}'
var storageName = toLower('st${baseName}${take(suffix, 10)}')
var almanacShareName = 'almanac-instance'
var environmentName = 'cae-${baseName}-${stage}'

resource appsIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: appsIdentityName
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// Network: one VNet, one subnet for the apps environment, one for PostgreSQL
// ---------------------------------------------------------------------------
resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.20.0.0/16'] }
    subnets: [
      {
        name: appsSubnetName
        properties: {
          addressPrefix: '10.20.0.0/23'
          delegations: [
            { name: 'containerapps', properties: { serviceName: 'Microsoft.App/environments' } }
          ]
          serviceEndpoints: [
            { service: 'Microsoft.Storage' }
            { service: 'Microsoft.KeyVault' }
          ]
        }
      }
      {
        name: postgresSubnetName
        properties: {
          addressPrefix: '10.20.2.0/24'
          delegations: [
            { name: 'postgres', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }
          ]
        }
      }
    ]
  }

  resource appsSubnet 'subnets' existing = {
    name: appsSubnetName
  }

  resource postgresSubnet 'subnets' existing = {
    name: postgresSubnetName
  }
}

// ---------------------------------------------------------------------------
// PostgreSQL Flexible Server: private to the VNet, no public endpoint, TLS only
// ---------------------------------------------------------------------------
resource postgresDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: postgresDnsZoneName
  location: 'global'
  tags: tags
}

resource postgresDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: postgresDns
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}

resource postgresNew 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = if (deployPostgres) {
  name: postgresName
  location: location
  tags: tags
  sku: {
    name: postgresSkuName
    tier: 'Burstable'
  }
  properties: {
    version: postgresVersion
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: postgresStorageGb
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    authConfig: {
      passwordAuth: 'Enabled' // pragma: allowlist secret
      activeDirectoryAuth: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: vnet::postgresSubnet.id
      privateDnsZoneArmResourceId: postgresDns.id
      publicNetworkAccess: 'Disabled'
    }
  }
  dependsOn: [postgresDnsLink]
}

// The server, whether created above or already there.
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: postgresName
}

resource databases 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = [
  for name in databaseNames: {
    parent: postgres
    dependsOn: [postgresNew]
    name: name
    properties: {
      charset: 'UTF8'
      collation: 'en_US.utf8'
    }
  }
]

// ---------------------------------------------------------------------------
// Key Vault: RBAC only, every application secret lives here
// ---------------------------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    // The Container Apps platform and GitHub Actions read/seed secrets over the
    // public endpoint; access is still gated by Entra RBAC.
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// Flexible Server hostnames are always <name>.postgres.database.azure.com (also with private access,
// through the linked private DNS zone), so this needs no runtime lookup of the server.
var postgresHost = '${postgresName}.postgres.database.azure.com'
var encodedPassword = uriComponent(postgresAdminPassword)
// The driver is named explicitly: the services ship psycopg2-binary, and newer
// SQLAlchemy releases map a bare postgresql:// to the psycopg (v3) driver instead.
var databaseUrlPrefix = 'postgresql+psycopg2://${postgresAdminLogin}:${encodedPassword}@${postgresHost}:5432/'
var secretValues = {
  'postgres-admin-password': postgresAdminPassword
  'auth-secret-key': authSecretKey
  'vgarden-secret-key': vgardenSecretKey
  'almanac-secret-key': almanacSecretKey
  'inter-service-secret': interServiceSecret
  'database-url-auth': '${databaseUrlPrefix}auth?sslmode=require'
  'database-url-vgarden': '${databaseUrlPrefix}vgarden?sslmode=require'
  'database-url-health': '${databaseUrlPrefix}health?sslmode=require'
  'database-url-almanac': '${databaseUrlPrefix}almanac?sslmode=require'
}

// The names are static (the loop must be sized before deployment starts); the
// values may depend on the PostgreSQL server, which is fine inside the body.
var secretNames = [
  'postgres-admin-password'
  'auth-secret-key'
  'vgarden-secret-key'
  'almanac-secret-key'
  'inter-service-secret'
  'database-url-auth'
  'database-url-vgarden'
  'database-url-health'
  'database-url-almanac'
]

resource secrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [
  for secretName in secretNames: {
    parent: keyVault
    name: secretName
    properties: {
      value: secretValues[secretName]
      contentType: 'text/plain'
    }
  }
]

// ---------------------------------------------------------------------------
// Container registry
// ---------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// Storage for the Almanac's uploaded plant images (mounted at /app/instance)
// ---------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    // The Container Apps environment mounts the share with the account key.
    allowSharedKeyAccess: true
    networkAcls: {
      defaultAction: storageRestrictToVnet ? 'Deny' : 'Allow'
      bypass: 'AzureServices'
      virtualNetworkRules: storageRestrictToVnet
        ? [
            { id: vnet::appsSubnet.id, action: 'Allow' }
          ]
        : []
    }
  }

  resource files 'fileServices' = {
    name: 'default'

    resource almanacShare 'shares' = {
      name: almanacShareName
      properties: {
        shareQuota: 5
        enabledProtocols: 'SMB'
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Container Apps environment (consumption, VNet-integrated, public ingress)
// ---------------------------------------------------------------------------
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: vnet::appsSubnet.id
      internal: false
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
    zoneRedundant: false
  }
}

resource almanacStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: environment
  name: almanacShareName
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: storage::files::almanacShare.name
      accessMode: 'ReadWrite'
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs consumed by apps.bicep (through scripts/deploy/azure-apps.sh)
// ---------------------------------------------------------------------------
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output environmentName string = environment.name
output environmentId string = environment.id
output environmentDefaultDomain string = environment.properties.defaultDomain
output environmentStaticIp string = environment.properties.staticIp
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output postgresName string = postgres.name
output postgresFqdn string = postgresHost
output storageAccountName string = storage.name
output almanacStorageName string = almanacStorage.name
output appsIdentityClientId string = appsIdentity.properties.clientId
output logAnalyticsWorkspaceId string = logs.properties.customerId
