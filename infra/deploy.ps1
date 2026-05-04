[CmdletBinding()]
param(
  [string]$Location = 'westeurope',
  [string]$Rg = 'rg-hybrid-latency-lab',
  [string]$Prefix = 'hyblat',
  [string]$SshKeyFile = "$env:USERPROFILE\.ssh\hyblat_id_ed25519.pub",
  [string]$PgPassword
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $SshKeyFile)) {
  throw "Missing SSH public key at $SshKeyFile"
}

if (-not $PgPassword) {
  $bytes = New-Object byte[] 18
  [void](New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
  $PgPassword = [Convert]::ToBase64String($bytes).Replace('/','').Replace('+','').Substring(0,20) + 'Aa1!'
  Write-Host "Generated PG password (save it): $PgPassword"
}

az group create -n $Rg -l $Location -o none

$sshPub = Get-Content $SshKeyFile -Raw
$deploymentName = "lab-{0}" -f (Get-Date -Format 'yyyyMMddHHmmss')

az deployment group create `
  -g $Rg `
  -n $deploymentName `
  -f "$PSScriptRoot/main.bicep" `
  -p location=$Location prefix=$Prefix sshPublicKey="$sshPub" pgAdminPassword="$PgPassword" `
  -o table
