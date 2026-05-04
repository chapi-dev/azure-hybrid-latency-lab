targetScope = 'resourceGroup'

@description('Azure region for hub, spoke, on-prem VNet, VMs, and DB. Single-region simulated hybrid lab.')
param location string = 'westeurope'

@description('Prefix for all resource names. Keep short.')
param prefix string = 'hyblat'

@description('Admin username for both Linux VMs.')
param adminUsername string = 'azureuser'

@description('SSH public key for both Linux VMs.')
@secure()
param sshPublicKey string

@description('PostgreSQL admin login.')
param pgAdminLogin string = 'pgadmin'

@description('PostgreSQL admin password.')
@secure()
param pgAdminPassword string

@description('Tags for all resources.')
param tags object = {
  lab: 'hybrid-latency'
  owner: 'antonioch'
  env: 'demo'
}

// Address spaces
var hubAddressPrefix = '10.0.0.0/24'
var spokeAddressPrefix = '10.10.0.0/16'
var onpremAddressPrefix = '10.100.0.0/16'

module obs 'modules/observability.bicep' = {
  name: 'observability'
  params: {
    location: location
    prefix: prefix
    tags: tags
  }
}

module vwan 'modules/vwan.bicep' = {
  name: 'vwan'
  params: {
    location: location
    prefix: prefix
    hubAddressPrefix: hubAddressPrefix
    tags: tags
  }
}

module spokeNet 'modules/spoke-network.bicep' = {
  name: 'spoke-network'
  params: {
    location: location
    prefix: prefix
    spokeAddressPrefix: spokeAddressPrefix
    hubId: vwan.outputs.hubId
    tags: tags
  }
}

module onpremNet 'modules/onprem-network.bicep' = {
  name: 'onprem-network'
  params: {
    location: location
    prefix: prefix
    onpremAddressPrefix: onpremAddressPrefix
    hubId: vwan.outputs.hubId
    tags: tags
  }
}

module vmSpoke 'modules/vm.bicep' = {
  name: 'vm-spoke'
  params: {
    location: location
    vmName: '${prefix}-vm-spoke'
    subnetId: spokeNet.outputs.vmSubnetId
    adminUsername: adminUsername
    sshPublicKey: sshPublicKey
    tags: tags
    enablePublicIp: true
  }
}

module vmOnprem 'modules/vm.bicep' = {
  name: 'vm-onprem'
  params: {
    location: location
    vmName: '${prefix}-vm-onprem'
    subnetId: onpremNet.outputs.vmSubnetId
    adminUsername: adminUsername
    sshPublicKey: sshPublicKey
    tags: tags
    enablePublicIp: true
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    location: location
    serverName: '${prefix}-pg-${uniqueString(resourceGroup().id)}'
    delegatedSubnetId: spokeNet.outputs.pgSubnetId
    privateDnsZoneId: spokeNet.outputs.pgDnsZoneId
    adminLogin: pgAdminLogin
    adminPassword: pgAdminPassword
    tags: tags
  }
}

output vmSpokePublicIp string = vmSpoke.outputs.publicIp
output vmSpokePrivateIp string = vmSpoke.outputs.privateIp
output vmOnpremPublicIp string = vmOnprem.outputs.publicIp
output vmOnpremPrivateIp string = vmOnprem.outputs.privateIp
output pgFqdn string = postgres.outputs.fqdn
output appInsightsConnectionString string = obs.outputs.appInsightsConnectionString
output logAnalyticsWorkspaceId string = obs.outputs.logAnalyticsWorkspaceId
output hubId string = vwan.outputs.hubId
