// One container app on the shared environment. Used six times by apps.bicep.
//
// Every app pulls from the registry and reads Key Vault secrets with the same
// user-assigned identity; nothing is stored as a plain secret on the app.

param name string
param location string
param environmentId string
param identityId string
param acrLoginServer string
param image string
param tags object = {}

@description('Public HTTPS ingress (the proxy) or internal-only (every service).')
param external bool = false

@description('Internal apps are reached over plain HTTP inside the environment; the public proxy redirects HTTP to HTTPS.')
param allowInsecure bool = !external

param targetPort int = 5000

@description('Overrides the image CMD, e.g. to run the Flask app under gunicorn.')
param command array = []

@description('Container environment: [{ name, value }] or [{ name, secretRef }].')
param env array = []

@description('Key Vault references: [{ name, keyVaultUrl }]. Exposed to the container through secretRef.')
param secrets array = []

param minReplicas int = 0
param maxReplicas int = 1

@allowed(['0.25', '0.5', '0.75', '1'])
param cpu string = '0.5'

@allowed(['0.5Gi', '1Gi', '1.5Gi', '2Gi'])
param memory string = '1Gi'

@description('HTTP path for the startup, liveness and readiness probes.')
param probePath string = '/'

@description('[{ volumeName, mountPath }] matching an entry in volumes.')
param volumeMounts array = []

@description('[{ name, storageType: AzureFile, storageName }] (environment storages).')
param volumes array = []

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: external
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: allowInsecure
        traffic: [
          { latestRevision: true, weight: 100 }
        ]
      }
      registries: [
        { server: acrLoginServer, identity: identityId }
      ]
      secrets: [
        for secret in secrets: {
          name: secret.name
          keyVaultUrl: secret.keyVaultUrl
          identity: identityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: name
          image: image
          command: empty(command) ? null : command
          env: env
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          probes: [
            {
              type: 'Startup'
              httpGet: { path: probePath, port: targetPort, scheme: 'HTTP' }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 10
              timeoutSeconds: 5
            }
            {
              type: 'Liveness'
              httpGet: { path: probePath, port: targetPort, scheme: 'HTTP' }
              periodSeconds: 30
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Readiness'
              httpGet: { path: probePath, port: targetPort, scheme: 'HTTP' }
              periodSeconds: 10
              failureThreshold: 3
              timeoutSeconds: 5
            }
          ]
          volumeMounts: volumeMounts
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http'
            http: { metadata: { concurrentRequests: '50' } }
          }
        ]
      }
      volumes: volumes
    }
  }
}

output name string = app.name
output fqdn string = app.properties.configuration.ingress.fqdn
output latestRevisionName string = app.properties.latestRevisionName
