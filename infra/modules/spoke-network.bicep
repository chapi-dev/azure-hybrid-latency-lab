param location string
param prefix string
param spokeAddressPrefix string
param hubId string
param tags object

var vmSubnetPrefix = cidrSubnet(spokeAddressPrefix, 24, 0)
var pgSubnetPrefix = cidrSubnet(spokeAddressPrefix, 24, 1)
var hubName = last(split(hubId, '/'))

resource nsgVm 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${prefix}-spoke-nsg-vm'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowSshFromInternet'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'AllowVnetIn'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${prefix}-spoke-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [ spokeAddressPrefix ]
    }
    subnets: [
      {
        name: 'snet-vm'
        properties: {
          addressPrefix: vmSubnetPrefix
          networkSecurityGroup: { id: nsgVm.id }
        }
      }
      {
        name: 'snet-pg'
        properties: {
          addressPrefix: pgSubnetPrefix
          delegations: [
            {
              name: 'pgflex'
              properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' }
            }
          ]
          serviceEndpoints: []
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource pgDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'private.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource pgDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  name: '${prefix}-spoke-link'
  parent: pgDnsZone
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource hub 'Microsoft.Network/virtualHubs@2023-11-01' existing = {
  name: hubName
}

resource hubConnection 'Microsoft.Network/virtualHubs/hubVirtualNetworkConnections@2023-11-01' = {
  parent: hub
  name: '${prefix}-spoke-conn'
  properties: {
    remoteVirtualNetwork: { id: vnet.id }
    allowHubToRemoteVnetTransit: true
    allowRemoteVnetToUseHubVnetGateways: false
    enableInternetSecurity: false
  }
}

output vnetId string = vnet.id
output vmSubnetId string = '${vnet.id}/subnets/snet-vm'
output pgSubnetId string = '${vnet.id}/subnets/snet-pg'
output pgDnsZoneId string = pgDnsZone.id
