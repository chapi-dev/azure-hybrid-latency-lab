param location string
param prefix string
param onpremAddressPrefix string
param hubId string
param tags object

var vmSubnetPrefix = cidrSubnet(onpremAddressPrefix, 24, 0)
var hubName = last(split(hubId, '/'))

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${prefix}-onprem-nsg'
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
  name: '${prefix}-onprem-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [ onpremAddressPrefix ]
    }
    subnets: [
      {
        name: 'snet-vm'
        properties: {
          addressPrefix: vmSubnetPrefix
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource hub 'Microsoft.Network/virtualHubs@2023-11-01' existing = {
  name: hubName
}

resource hubConnection 'Microsoft.Network/virtualHubs/hubVirtualNetworkConnections@2023-11-01' = {
  parent: hub
  name: '${prefix}-onprem-conn'
  properties: {
    remoteVirtualNetwork: { id: vnet.id }
    allowHubToRemoteVnetTransit: true
    allowRemoteVnetToUseHubVnetGateways: false
    enableInternetSecurity: false
  }
}

output vnetId string = vnet.id
output vmSubnetId string = '${vnet.id}/subnets/snet-vm'
