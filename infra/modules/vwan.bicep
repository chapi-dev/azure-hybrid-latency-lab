param location string
param prefix string
param hubAddressPrefix string
param tags object

resource vwan 'Microsoft.Network/virtualWans@2023-11-01' = {
  name: '${prefix}-vwan'
  location: location
  tags: tags
  properties: {
    type: 'Standard'
    allowBranchToBranchTraffic: true
    disableVpnEncryption: false
  }
}

resource hub 'Microsoft.Network/virtualHubs@2023-11-01' = {
  name: '${prefix}-hub'
  location: location
  tags: tags
  properties: {
    addressPrefix: hubAddressPrefix
    sku: 'Standard'
    virtualWan: {
      id: vwan.id
    }
  }
}

output vwanId string = vwan.id
output hubId string = hub.id
output hubName string = hub.name
